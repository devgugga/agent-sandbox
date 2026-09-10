"""cli/asb/supervisor.py — systemd user supervision and unit lifecycle.

Supervisiona containers persistentes via systemd --user Type=exec com podman start --attach.
Garante:
- Nenhuma referência ao caminho do checkout nas unidades renderizadas.
- Escaping estrito de % e espaços na sintaxe do systemd.
- Ausência de newlines nos nomes de containers/unidades.
- Gravação atômica em ~/.config/systemd/user/.
- Target regular habilitável para o workspace.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import podman
from .install import install_runtime

__all__ = [
    "ContainerUnit",
    "render_unit",
    "render_target",
    "install_runtime",
    "install_workspace",
    "start_workspace",
    "stop_workspace",
    "remove_workspace_units",
    "escape_systemd_arg",
    "adopt_workspace",
    "rollback_workspace",
    "adopt_keyring",
    "rollback_keyring",
]


@dataclass(frozen=True)
class ContainerUnit:
    name: str
    container_id: str
    role: str
    unit_name: str
    target_name: str
    helper_path: Path
    manifest_path: Path
    extra_after: tuple[str, ...] = ()
    extra_wants: tuple[str, ...] = ()
    include_readiness_check: bool = True

    def __post_init__(self) -> None:
        for field_name in ("name", "container_id", "role", "unit_name", "target_name"):
            val = getattr(self, field_name)
            if not isinstance(val, str):
                raise TypeError(f"{field_name} must be a string, got {type(val).__name__}")
            if "\n" in val or "\r" in val:
                raise ValueError(f"{field_name} cannot contain newline characters: {val!r}")

        for path_field in ("helper_path", "manifest_path"):
            pval = getattr(self, path_field)
            if "\n" in str(pval) or "\r" in str(pval):
                raise ValueError(f"{path_field} cannot contain newline characters: {pval!r}")


def escape_systemd_arg(value: str | Path) -> str:
    """Escapa % para %% e envolve em aspas duplas argumentos com espaços ou aspas."""
    s = str(value).replace("%", "%%")
    if any(c in s for c in ' \t\n\r"'):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


def render_unit(unit: ContainerUnit) -> str:
    """Renderiza a unidade systemd Type=exec para o container especificado."""
    target = (
        unit.target_name
        if unit.target_name.endswith(".target")
        else f"{unit.target_name}.target"
    )
    target_base = target.removesuffix(".target")

    # Dependências e ordenação
    if unit.role == "agent":
        proxy_unit = f"{target_base}-proxy.service"
        keyring_unit = "asb-keyring.service"
        after_deps = tuple(dict.fromkeys((proxy_unit, keyring_unit) + unit.extra_after))
        wants_deps = tuple(dict.fromkeys((proxy_unit, keyring_unit) + unit.extra_wants))
    else:
        after_deps = unit.extra_after
        wants_deps = unit.extra_wants

    after_line = f"After={' '.join(after_deps)}\n" if after_deps else ""
    wants_line = f"Wants={' '.join(wants_deps)}\n" if wants_deps else ""

    podman_bin = shutil.which("podman") or "/usr/bin/podman"

    helper_escaped = escape_systemd_arg(unit.helper_path)
    name_escaped = escape_systemd_arg(unit.name)
    podman_escaped = escape_systemd_arg(podman_bin)

    exec_start = f"{helper_escaped} start --attach --sig-proxy=false {name_escaped}"

    # ExecStartPost para verificação de prontidão
    exec_start_post_line = ""
    if unit.include_readiness_check and unit.role in ("proxy", "agent"):
        check_path = (
            unit.helper_path / "runtime_check.py"
            if unit.helper_path.is_dir()
            else unit.helper_path.parent / "runtime_check.py"
        )
        exec_start_post_line = (
            f"ExecStartPost={escape_systemd_arg(check_path)} "
            f"--role {unit.role} "
            f"--manifest {escape_systemd_arg(unit.manifest_path)}\n"
        )

    return (
        "[Unit]\n"
        f"Description=Agent Sandbox container {unit.name} ({unit.role})\n"
        f"PartOf={target}\n"
        f"{after_line}"
        f"{wants_line}"
        "StartLimitIntervalSec=600s\n"
        "StartLimitBurst=3\n"
        "\n"
        "[Service]\n"
        "Type=exec\n"
        f"ExecStart={exec_start}\n"
        f"{exec_start_post_line}"
        f"ExecStop={podman_escaped} stop --ignore --time=10 {name_escaped}\n"
        f"ExecStopPost={podman_escaped} stop --ignore --time=10 {name_escaped}\n"
        "Restart=always\n"
        "RestartSec=5s\n"
        "TimeoutStartSec=150s\n"
        "TimeoutStopSec=20s\n"
        "KillMode=process\n"
    )


def render_target(
    target_name: str,
    units: list[str] | None = None,
    description: str = "",
) -> str:
    """Renderiza a unidade .target agregadora para o workspace."""
    target = (
        target_name
        if target_name.endswith(".target")
        else f"{target_name}.target"
    )
    desc = description or f"Agent Sandbox workspace target for {target.removesuffix('.target')}"
    wants_line = f"Wants={' '.join(units)}\nAfter={' '.join(units)}\n" if units else ""
    return (
        "[Unit]\n"
        f"Description={desc}\n"
        f"{wants_line}"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _atomic_write_text(path: Path, content: str) -> None:
    """Grava o conteúdo de forma atômica no caminho de destino."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp.{os.getpid()}"
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def install_workspace(
    ws: str,
    target_dir: Path | None = None,
    state_dir: Path | None = None,
    helper_path: Path | None = None,
) -> list[Path]:
    """Instala as unidades systemd do workspace e executa daemon-reload."""
    if not ws or "\n" in ws or "\r" in ws:
        raise ValueError(f"Nome de workspace invalido: {ws!r}")

    state_path = (
        state_dir
        if state_dir is not None
        else (Path.home() / ".local" / "state" / "agent-sandbox" / ws)
    )
    manifest_file = state_path / "runtime.json"
    if not manifest_file.is_file():
        raise FileNotFoundError(f"Manifesto de runtime nao encontrado em: {manifest_file}")

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Falha ao ler manifesto {manifest_file}: {exc}") from exc

    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ValueError(f"Manifesto invalido em {manifest_file}: esperado schemaVersion 1")

    target_path = (
        target_dir
        if target_dir is not None
        else (Path.home() / ".config" / "systemd" / "user")
    )
    target_path.mkdir(parents=True, exist_ok=True)

    if helper_path is None:
        revision = manifest.get("revision")
        if revision:
            helper_path = (
                Path.home()
                / ".local"
                / "lib"
                / "agent-sandbox"
                / "runtime"
                / revision
                / "launcher.sh"
            )
        else:
            helper_path = Path(shutil.which("podman") or "/usr/bin/podman")

    target_name = f"asb-{ws}.target"
    containers = manifest.get("containers", {})
    if not isinstance(containers, dict) or not containers:
        raise ValueError(f"Manifesto {manifest_file} nao contem containers validos")

    written_files: list[Path] = []
    unit_names: list[str] = []

    for role, info in containers.items():
        if isinstance(info, dict):
            c_name = info.get("name") or f"asb-{ws}-{role}"
            c_id = info.get("id") or ""
            u_name = info.get("unit") or f"asb-{ws}-{role}.service"
        elif isinstance(info, str):
            c_name = info
            c_id = ""
            u_name = f"{info}.service"
        else:
            continue

        unit = ContainerUnit(
            name=c_name,
            container_id=c_id,
            role=role,
            unit_name=u_name,
            target_name=target_name,
            helper_path=helper_path,
            manifest_path=manifest_file,
        )
        content = render_unit(unit)
        unit_file = target_path / u_name
        _atomic_write_text(unit_file, content)
        written_files.append(unit_file)
        unit_names.append(u_name)

    # Renderizar unidade target
    target_content = render_target(target_name, units=unit_names)
    target_file = target_path / target_name
    _atomic_write_text(target_file, target_content)
    written_files.append(target_file)

    # Recarregar daemon
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)

    return written_files


def start_workspace(ws: str, *, enable: bool = False) -> None:
    """Inicia a unidade target do workspace via systemctl --user start."""
    target = ws if ws.endswith(".target") else f"asb-{ws}.target"
    if enable:
        subprocess.run(["systemctl", "--user", "enable", target], check=True)
    subprocess.run(["systemctl", "--user", "start", target], check=True)


def stop_workspace(ws: str, *, disable: bool = False) -> None:
    """Para a unidade target do workspace via systemctl --user stop."""
    target = ws if ws.endswith(".target") else f"asb-{ws}.target"
    subprocess.run(["systemctl", "--user", "stop", target], check=True)
    if disable:
        subprocess.run(["systemctl", "--user", "disable", target], check=True)


def remove_workspace_units(
    ws: str,
    target_dir: Path | None = None,
    state_dir: Path | None = None,
) -> None:
    """Desabilita, para e remove unidades do workspace do systemd.

    As unidades de servico sao identificadas EXCLUSIVAMENTE pelos nomes
    gravados no manifesto `runtime.json` do workspace — NUNCA por glob de
    prefixo. Um glob `asb-{ws}-*.service` casa tambem workspaces irmaos cujo
    nome comeca com o mesmo prefixo sem delimitador (ex: `asb-demo-` casa
    `asb-demo-2-agent.service`), removendo unidades de outro workspace. Esse
    e o mesmo bug de prefixo ja documentado em `_sweep_containers`
    (lifecycle.py), que usa LABEL em vez de prefixo pelo mesmo motivo.
    """
    target = ws if ws.endswith(".target") else f"asb-{ws}.target"
    target_path = (
        target_dir
        if target_dir is not None
        else (Path.home() / ".config" / "systemd" / "user")
    )
    state_path = (
        state_dir
        if state_dir is not None
        else (Path.home() / ".local" / "state" / "agent-sandbox" / ws)
    )

    # Parar e desabilitar target
    subprocess.run(
        ["systemctl", "--user", "stop", target],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["systemctl", "--user", "disable", target],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Coletar nomes EXATOS de unidade de servico a partir do manifesto do
    # proprio workspace. Sem manifesto (ou sem containers validos), nao ha
    # como saber quais nomes pertencem a este workspace — nada e removido
    # por adivinhacao/glob.
    unit_names: list[str] = []
    manifest_file = state_path / "runtime.json"
    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            manifest = None
        if isinstance(manifest, dict):
            containers = manifest.get("containers", {})
            if isinstance(containers, dict):
                for role, info in containers.items():
                    if isinstance(info, dict):
                        u_name = info.get("unit") or f"asb-{ws}-{role}.service"
                    elif isinstance(info, str):
                        u_name = f"{info}.service"
                    else:
                        continue
                    if u_name and "\n" not in u_name and "\r" not in u_name and "/" not in u_name:
                        unit_names.append(u_name)

    # Remover arquivos de unidade
    if target_path.is_dir():
        target_file = target_path / target
        if target_file.is_file():
            target_file.unlink()

        for u_name in unit_names:
            svc_file = target_path / u_name
            if svc_file.is_file():
                svc_file.unlink()

    # Recarregar daemon
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)


# ==============================================================================
# Adoção e Rollback de Workspace e Keyring (Tarefa I6)
# ==============================================================================

def _resolve_paths(
    ws: str = "",
    target_dir: Path | None = None,
    state_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Resolve state_path e target_path respeitando ASB_STATE_ROOT e defaults."""
    state_base = (
        Path(os.environ["ASB_STATE_ROOT"])
        if "ASB_STATE_ROOT" in os.environ
        else (Path.home() / ".local" / "state" / "agent-sandbox")
    )
    if state_dir is not None:
        state_path = state_dir
    elif ws:
        state_path = state_base / ws
    else:
        state_path = state_base

    target_path = (
        target_dir
        if target_dir is not None
        else (Path.home() / ".config" / "systemd" / "user")
    )
    return state_path, target_path


class _AdoptionLock:
    """Context manager para lock exclusivo não-bloqueante (fail-closed)."""

    def __init__(self, lock_file: Path, component_name: str) -> None:
        self.lock_file = lock_file
        self.component_name = component_name
        self.fd: int | None = None

    def __enter__(self) -> _AdoptionLock:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(str(self.lock_file), os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            if self.fd is not None:
                try:
                    os.close(self.fd)
                except Exception:
                    pass
                self.fd = None
            raise RuntimeError(
                f"lock ocupado ({self.lock_file}): outro processo esta operando '{self.component_name}'"
            ) from exc
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None


def _ensure_launcher_script(state_path: Path, helper_path: Path | None = None) -> Path:
    """Resolve ou cria um launcher.sh executável para evitar a regressão R9."""
    if helper_path is not None and helper_path.is_file():
        return helper_path
    if "ASB_LAUNCHER_PATH" in os.environ:
        env_p = Path(os.environ["ASB_LAUNCHER_PATH"])
        if env_p.is_file():
            return env_p

    # 1. Procurar em runtimes instalados ~/.local/lib/agent-sandbox/runtime/*/launcher.sh
    runtime_root = Path.home() / ".local" / "lib" / "agent-sandbox" / "runtime"
    if runtime_root.is_dir():
        for d in sorted(runtime_root.iterdir(), reverse=True):
            cand = d / "launcher.sh"
            if cand.is_file():
                return cand

    # 2. Se não encontrado, gerar launcher.sh seguro no state_path
    launcher_file = state_path / "launcher.sh"
    if not launcher_file.is_file():
        podman_bin = shutil.which("podman") or "/usr/bin/podman"
        content = (
            "#!/bin/sh\n"
            "set -eu\n"
            f'podman_bin="{podman_bin}"\n'
            'container=""\n'
            'for arg in "$@"; do\n'
            '    case "$arg" in\n'
            "        --attach|--sig-proxy=false|--sig-proxy=*|start)\n"
            "            ;;\n"
            "        *)\n"
            '            container="$arg"\n'
            "            ;;\n"
            "    esac\n"
            "done\n"
            'if [ -z "$container" ]; then\n'
            '    echo "asb-launcher: missing container name" >&2\n'
            "    exit 2\n"
            "fi\n"
            'status=$("$podman_bin" inspect "$container" --format \'{{.State.Status}}\' 2>/dev/null || true)\n'
            'if [ "$status" = "running" ]; then\n'
            '    exec "$podman_bin" attach --sig-proxy=false "$container"\n'
            "else\n"
            '    exec "$podman_bin" start --attach --sig-proxy=false "$container"\n'
            "fi\n"
        )
        _atomic_write_text(launcher_file, content)
        launcher_file.chmod(0o755)
    return launcher_file


def _inspect_workspace_containers(ws: str) -> dict[str, dict[str, object]]:
    """Inventaria estritamente containers pertencentes ao workspace pelo label exato."""
    names_raw = podman.out("ps", "-a", "--filter", f"label=asb.workspace={ws}", "--format", "{{.Names}}")
    names = [n.strip() for n in names_raw.splitlines() if n.strip()]
    if not names:
        raise ValueError(f"nenhum container encontrado para o workspace '{ws}'")

    containers: dict[str, dict[str, object]] = {}
    for name in names:
        raw = podman.out("container", "inspect", name, "--format", "{{json .}}")
        data = json.loads(raw)
        cid = data.get("Id", "")
        cfg = data.get("Config", {})
        labels = cfg.get("Labels", {}) or {}
        role = labels.get("asb.role") or ""
        if not role:
            if name.endswith("-agent") or name.endswith("-pilot"):
                role = "agent"
            elif name.endswith("-proxy"):
                role = "proxy"
            elif name.endswith("-forwarder") or name.endswith("-fwd"):
                role = "forwarder"
            elif name.endswith("-docker"):
                role = "docker"
            else:
                role = name.rsplit("-", 1)[-1]

        state = data.get("State", {})
        status = "running" if state.get("Running") else (state.get("Status") or "stopped")
        host_cfg = data.get("HostConfig", {})
        policy = (host_cfg.get("RestartPolicy", {}) or {}).get("Name") or "unless-stopped"
        image = cfg.get("Image", "")

        ports = []
        network_settings = data.get("NetworkSettings", {})
        ports_dict = network_settings.get("Ports", {}) or {}
        for container_port, host_confs in ports_dict.items():
            if host_confs:
                for hc in host_confs:
                    hport = hc.get("HostPort")
                    if hport:
                        ports.append({"container_port": container_port, "host_port": hport})

        unit_name = f"asb-{ws}-{role}.service"
        containers[role] = {
            "id": cid,
            "name": name,
            "role": role,
            "image": image,
            "prior_state": status,
            "prior_restart_policy": policy,
            "ports": ports,
            "unit_name": unit_name,
        }
    return containers


def _verify_journal_id_parity(containers: dict[str, dict[str, object]], journal: dict[str, object]) -> None:
    """Verifica se os IDs atuais coincidem estritamente com os IDs gravados no diário."""
    journal_containers = journal.get("containers", {})
    if isinstance(journal_containers, dict):
        if set(journal_containers.keys()) != set(containers.keys()):
            raise ValueError(
                f"Conjunto de containers divergente: registrado {sorted(journal_containers.keys())}, atual {sorted(containers.keys())}"
            )
        for role, j_info in journal_containers.items():
            if isinstance(j_info, dict):
                jid = j_info.get("id")
                if role in containers:
                    cid = containers[role].get("id")
                    if jid and cid and jid != cid:
                        raise ValueError(
                            f"ID divergente para container '{role}': registrado {jid}, atual {cid}"
                        )


def _is_container_running(c_target: str) -> bool:
    """Verifica se um container está em execução por nome ou ID."""
    try:
        return podman.out("inspect", c_target, "--format", "{{.State.Running}}").strip() == "true"
    except Exception:
        return False


def _collect_diagnostics(ws: str) -> dict[str, object]:
    """Coleta diagnósticos de coexistência: layout de credenciais, forwarder e netns."""
    cred_vol_candidates = [
        os.environ.get("ASB_CREDENTIALS_VOLUME"),
        f"asb-{ws}-credentials",
        f"asb-test-{ws}-credentials",
        f"{ws}-credentials",
    ]
    legacy_cred = False
    for cred_vol in cred_vol_candidates:
        if cred_vol and podman.exists("volume", cred_vol):
            try:
                mp = podman.out("volume", "inspect", cred_vol, "--format", "{{.Mountpoint}}").strip()
                if mp and Path(mp).is_dir():
                    root_files = [f.name for f in Path(mp).iterdir() if f.is_file()]
                    if any(rf in root_files for rf in (".credentials.json", "credentials.json", "auth.json")):
                        legacy_cred = True
                break
            except Exception:
                pass

    fwd_needs_rec = False
    fwd_candidates = [
        os.environ.get("ASB_FORWARDER_CONTAINER"),
        f"asb-{ws}-forwarder",
        f"asb-test-{ws}-forwarder",
        f"{ws}-forwarder",
    ]
    for fwd_name in fwd_candidates:
        if fwd_name and podman.exists("container", fwd_name):
            try:
                raw_inspect = podman.out("inspect", fwd_name)
                if "net.ipv4.ip_unprivileged_port_start" not in raw_inspect:
                    fwd_needs_rec = True
                break
            except Exception:
                pass

    netns_producers = []
    dropin = Path.home() / ".config" / "systemd" / "user" / "podman-restart.service.d" / "agent-sandbox.conf"
    if dropin.is_file():
        netns_producers.append("podman-restart.service.d/agent-sandbox.conf")
    try:
        other_workspaces = set()
        for line in podman.out("ps", "--format", "{{.Labels}}").splitlines():
            for item in line.split(","):
                if item.startswith("asb.workspace="):
                    other_workspaces.add(item.split("=", 1)[1])
        if other_workspaces:
            netns_producers.append(f"workspaces_ativos:{len(other_workspaces)}")
    except Exception:
        pass

    return {
        "legacy_credentials_layout": legacy_cred,
        "forwarder_needs_recreation": fwd_needs_rec,
        "rootless_netns_producers": netns_producers,
    }


def _rollback_workspace_from_journal(
    ws: str,
    journal: dict[str, object],
    state_path: Path,
    target_path: Path,
) -> None:
    """Restaura políticas e unidades de workspace a partir do diário sem recriar containers."""
    target_name = f"asb-{ws}.target"

    subprocess.run(
        ["systemctl", "--user", "stop", target_name],
        check=False,
        capture_output=True,
    )

    prior_units = journal.get("prior_units", {})
    if isinstance(prior_units, dict):
        if not prior_units.get("target_enabled", False):
            subprocess.run(
                ["systemctl", "--user", "disable", target_name],
                check=False,
                capture_output=True,
            )

        services = prior_units.get("services", {})
        if isinstance(services, dict):
            for u_name, s_info in services.items():
                if isinstance(s_info, dict) and not s_info.get("existed", False):
                    svc_file = target_path / u_name
                    if svc_file.is_file():
                        svc_file.unlink()

        if not prior_units.get("target_existed", False):
            target_file = target_path / target_name
            if target_file.is_file():
                target_file.unlink()

    containers = journal.get("containers", {})
    if isinstance(containers, dict):
        for role, c_info in containers.items():
            if isinstance(c_info, dict):
                cid = str(c_info.get("id", ""))
                policy = str(c_info.get("prior_restart_policy") or "unless-stopped")
                if cid:
                    podman.run("update", f"--restart={policy}", cid, check=False)
                    prior_state = c_info.get("prior_state")
                    is_running = _is_container_running(cid)
                    if prior_state == "running" and not is_running:
                        podman.run("start", cid, check=False)
                    elif prior_state != "running" and is_running:
                        podman.run("stop", "-t", "5", cid, check=False)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)

    manifest_file = state_path / "runtime.json"
    if manifest_file.is_file():
        try:
            m = json.loads(manifest_file.read_text(encoding="utf-8"))
            if isinstance(m, dict):
                m["runtime_type"] = "legacy"
                m["runtime_backend"] = "legacy"
                _atomic_write_text(manifest_file, json.dumps(m, indent=2))
        except Exception:
            pass


def adopt_workspace(
    ws: str,
    *,
    apply: bool = False,
    target_dir: Path | None = None,
    state_dir: Path | None = None,
    helper_path: Path | None = None,
    include_readiness_check: bool = False,
) -> dict[str, object]:
    """Adota supervisão systemd Type=exec sem recriar containers (schema 1)."""
    if not ws or "\n" in ws or "\r" in ws or "/" in ws or " " in ws:
        raise ValueError(f"Nome de workspace invalido: {ws!r}")

    state_path, target_path = _resolve_paths(ws, target_dir, state_dir)
    lock_path = state_path / ".adopt.lock"

    with _AdoptionLock(lock_path, ws):
        containers = _inspect_workspace_containers(ws)

        target_name = f"asb-{ws}.target"
        target_file = target_path / target_name
        target_existed = target_file.is_file()
        target_enabled = subprocess.run(
            ["systemctl", "--user", "is-enabled", target_name],
            capture_output=True,
        ).returncode == 0
        target_active = subprocess.run(
            ["systemctl", "--user", "is-active", target_name],
            capture_output=True,
        ).returncode == 0

        services: dict[str, dict[str, object]] = {}
        for role, c_info in containers.items():
            u_name = str(c_info["unit_name"])
            u_file = target_path / u_name
            u_existed = u_file.is_file()
            u_enabled = subprocess.run(
                ["systemctl", "--user", "is-enabled", u_name],
                capture_output=True,
            ).returncode == 0
            u_active = subprocess.run(
                ["systemctl", "--user", "is-active", u_name],
                capture_output=True,
            ).returncode == 0
            services[u_name] = {
                "file": str(u_file),
                "existed": u_existed,
                "enabled": u_enabled,
                "active": u_active,
            }

        diag = _collect_diagnostics(ws)

        journal_file = state_path / "journal.json"
        existing_journal = None
        if journal_file.is_file():
            try:
                existing_journal = json.loads(journal_file.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ValueError(f"diario corrompido em {journal_file}: {exc}") from exc
            if not isinstance(existing_journal, dict) or existing_journal.get("schemaVersion") != 1:
                raise ValueError(f"schemaVersion incompativel ou diario invalido em {journal_file}")
            _verify_journal_id_parity(containers, existing_journal)

        # Se ja existe um diario previo valido (ex: retomada ou re-execucao),
        # preservamos o baseline pre-adocao para que o rollback nao seja corrompido.
        if isinstance(existing_journal, dict) and existing_journal.get("phase") != "rolled_back":
            prior_units = existing_journal.get("prior_units", {
                "target_file": str(target_file),
                "target_existed": target_existed,
                "target_enabled": target_enabled,
                "target_active": target_active,
                "services": services,
            })
            for role, c_info in containers.items():
                orig_c = (existing_journal.get("containers") or {}).get(role)
                if isinstance(orig_c, dict):
                    if "prior_restart_policy" in orig_c:
                        c_info["prior_restart_policy"] = orig_c["prior_restart_policy"]
                    if "prior_state" in orig_c:
                        c_info["prior_state"] = orig_c["prior_state"]
        else:
            prior_units = {
                "target_file": str(target_file),
                "target_existed": target_existed,
                "target_enabled": target_enabled,
                "target_active": target_active,
                "services": services,
            }

        inventory: dict[str, object] = {
            "schemaVersion": 1,
            "workspace": ws,
            "containers": containers,
            "prior_units": prior_units,
            "diagnostics": diag,
            "phase": "inventory",
        }

        if not apply:
            return {
                "status": "dry_run",
                "workspace": ws,
                "inventory": inventory,
            }

        journal = dict(inventory)
        _atomic_write_text(journal_file, json.dumps(journal, indent=2))

        try:
            manifest_file = state_path / "runtime.json"
            manifest_data = {
                "schemaVersion": 1,
                "workspace": ws,
                "runtime_type": "systemd",
                "runtime_backend": "systemd",
                "containers": {
                    role: {
                        "name": c["name"],
                        "id": c["id"],
                        "unit": c["unit_name"],
                    }
                    for role, c in containers.items()
                },
            }
            _atomic_write_text(manifest_file, json.dumps(manifest_data, indent=2))

            resolved_helper = _ensure_launcher_script(state_path, helper_path)

            unit_names = []
            for role, c in containers.items():
                unit = ContainerUnit(
                    name=str(c["name"]),
                    container_id=str(c["id"]),
                    role=role,
                    unit_name=str(c["unit_name"]),
                    target_name=target_name,
                    helper_path=resolved_helper,
                    manifest_path=manifest_file,
                    include_readiness_check=include_readiness_check,
                )
                rendered = render_unit(unit)
                u_file = target_path / str(c["unit_name"])
                _atomic_write_text(u_file, rendered)
                unit_names.append(str(c["unit_name"]))

            rendered_target = render_target(target_name, units=unit_names)
            _atomic_write_text(target_file, rendered_target)

            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            journal["phase"] = "units_prepared"
            _atomic_write_text(journal_file, json.dumps(journal, indent=2))

            fresh_containers = _inspect_workspace_containers(ws)
            _verify_journal_id_parity(fresh_containers, journal)

            for role, c in containers.items():
                cid = str(c["id"])
                podman.run("update", "--restart=no", cid)

            journal["phase"] = "policies_updated"
            _atomic_write_text(journal_file, json.dumps(journal, indent=2))

            any_running = any(c["prior_state"] == "running" for c in containers.values())
            if not any_running:
                journal["phase"] = "supervision_configured"
                _atomic_write_text(journal_file, json.dumps(journal, indent=2))
            else:
                subprocess.run(["systemctl", "--user", "enable", target_name], check=True)
                start_workspace(ws)
                journal["phase"] = "supervision_started"
                _atomic_write_text(journal_file, json.dumps(journal, indent=2))

                res_act = subprocess.run(["systemctl", "--user", "is-active", target_name], capture_output=True, text=True)
                if res_act.stdout.strip() != "active":
                    raise RuntimeError(f"target {target_name} nao esta ativo apos start: {res_act.stdout.strip()}")

                for role, c in containers.items():
                    target_id = str(c.get("id", c.get("name", "")))
                    if c.get("prior_state") == "running" and not _is_container_running(target_id):
                        raise RuntimeError(f"container {role} ({c['id']}) nao esta em execucao apos adocao")

                journal["phase"] = "readiness_verified"
                _atomic_write_text(journal_file, json.dumps(journal, indent=2))

            return {
                "status": "applied",
                "workspace": ws,
                "phase": journal["phase"],
                "inventory": inventory,
            }

        except Exception as exc:
            journal["error"] = {"type": type(exc).__name__, "message": str(exc)}
            _atomic_write_text(journal_file, json.dumps(journal, indent=2))
            _rollback_workspace_from_journal(ws, journal, state_path, target_path)
            raise


def rollback_workspace(
    ws: str,
    *,
    target_dir: Path | None = None,
    state_dir: Path | None = None,
) -> dict[str, object]:
    """Reverte supervisão systemd de um workspace para legacy sem recriar containers."""
    if not ws or "\n" in ws or "\r" in ws or "/" in ws or " " in ws:
        raise ValueError(f"Nome de workspace invalido: {ws!r}")

    state_path, target_path = _resolve_paths(ws, target_dir, state_dir)
    lock_path = state_path / ".adopt.lock"

    with _AdoptionLock(lock_path, ws):
        journal_file = state_path / "journal.json"
        if not journal_file.is_file():
            raise FileNotFoundError(f"diario ausente em {journal_file}: impossivel determinar estado anterior para rollback")

        try:
            journal = json.loads(journal_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"diario corrompido em {journal_file}: {exc}") from exc

        if not isinstance(journal, dict) or journal.get("schemaVersion") != 1:
            raise ValueError(f"schemaVersion incompativel ou diario invalido em {journal_file}")

        fresh_containers = _inspect_workspace_containers(ws)
        _verify_journal_id_parity(fresh_containers, journal)

        _rollback_workspace_from_journal(ws, journal, state_path, target_path)

        journal["phase"] = "rolled_back"
        _atomic_write_text(journal_file, json.dumps(journal, indent=2))

        return {"status": "rolled_back", "workspace": ws}


def _inspect_keyring_container_info(container_name: str) -> dict[str, object]:
    """Inspeciona estritamente o container do keyring."""
    if not podman.exists("container", container_name):
        raise ValueError(f"container de keyring '{container_name}' nao encontrado")

    raw = podman.out("container", "inspect", container_name, "--format", "{{json .}}")
    data = json.loads(raw)
    cid = data.get("Id", "")
    cfg = data.get("Config", {})
    state = data.get("State", {})
    status = "running" if state.get("Running") else (state.get("Status") or "stopped")
    host_cfg = data.get("HostConfig", {})
    policy = (host_cfg.get("RestartPolicy", {}) or {}).get("Name") or "unless-stopped"
    image = cfg.get("Image", "")

    return {
        "id": cid,
        "name": container_name,
        "prior_state": status,
        "prior_restart_policy": policy,
        "image": image,
    }


def _render_keyring_unit(c_name: str, helper_path: Path) -> str:
    """Renderiza a unidade systemd Type=exec do keyring singleton."""
    helper_escaped = escape_systemd_arg(helper_path)
    name_escaped = escape_systemd_arg(c_name)
    podman_bin = shutil.which("podman") or "/usr/bin/podman"
    podman_escaped = escape_systemd_arg(podman_bin)
    return (
        "[Unit]\n"
        f"Description=Agent Sandbox Secret Service keyring singleton\n"
        "Documentation=https://github.com/devgugga/agent-sandbox\n"
        "StartLimitIntervalSec=600s\n"
        "StartLimitBurst=3\n"
        "\n"
        "[Service]\n"
        "Type=exec\n"
        f"ExecStart={helper_escaped} start --attach --sig-proxy=false {name_escaped}\n"
        f"ExecStop={podman_escaped} stop --ignore --time=10 {name_escaped}\n"
        f"ExecStopPost={podman_escaped} stop --ignore --time=10 {name_escaped}\n"
        "Restart=always\n"
        "RestartSec=5s\n"
        "TimeoutStartSec=150s\n"
        "TimeoutStopSec=20s\n"
        "KillMode=process\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _rollback_keyring_from_journal(
    journal: dict[str, object],
    target_path: Path,
) -> None:
    """Restaura o estado anterior do keyring sem recriar containers."""
    unit_name = "asb-keyring.service"
    unit_file = target_path / unit_name

    subprocess.run(["systemctl", "--user", "stop", unit_name], check=False, capture_output=True)
    subprocess.run(["systemctl", "--user", "disable", unit_name], check=False, capture_output=True)

    prior_unit = journal.get("prior_unit", {})
    if isinstance(prior_unit, dict) and not prior_unit.get("existed", False):
        if unit_file.is_file():
            unit_file.unlink()

    container_info = journal.get("container", {})
    if isinstance(container_info, dict):
        cid = str(container_info.get("id", ""))
        policy = str(container_info.get("prior_restart_policy") or "unless-stopped")
        if cid:
            podman.run("update", f"--restart={policy}", cid, check=False)
            prior_state = container_info.get("prior_state")
            is_running = _is_container_running(cid)
            if prior_state == "running" and not is_running:
                podman.run("start", cid, check=False)
            elif prior_state != "running" and is_running:
                podman.run("stop", "-t", "5", cid, check=False)

    prior_dropin = journal.get("prior_dropin", {})
    if isinstance(prior_dropin, dict) and prior_dropin.get("removed_by_adoption", False):
        from .install import restore_project_dropin
        restore_project_dropin(target_path)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


def adopt_keyring(
    *,
    apply: bool = False,
    target_dir: Path | None = None,
    state_dir: Path | None = None,
) -> dict[str, object]:
    """Adota o keyring singleton sob supervisão systemd sem recriar containers."""
    state_path, target_path = _resolve_paths("", target_dir, state_dir)
    lock_path = state_path / ".keyring-adopt.lock"
    c_name = os.environ.get("ASB_KEYRING_CONTAINER", "asb-keyring")

    with _AdoptionLock(lock_path, "keyring"):
        info = _inspect_keyring_container_info(c_name)

        unit_name = "asb-keyring.service"
        unit_file = target_path / unit_name
        unit_existed = unit_file.is_file()
        unit_enabled = subprocess.run(
            ["systemctl", "--user", "is-enabled", unit_name],
            capture_output=True,
        ).returncode == 0
        unit_active = subprocess.run(
            ["systemctl", "--user", "is-active", unit_name],
            capture_output=True,
        ).returncode == 0

        from .install import check_project_dropin, remove_project_dropin
        dropin_exists, dropin_ours = check_project_dropin(target_path)

        journal_file = state_path / "keyring-journal.json"
        existing_journal = None
        if journal_file.is_file():
            try:
                existing_journal = json.loads(journal_file.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ValueError(f"diario de keyring corrompido: {exc}") from exc
            if not isinstance(existing_journal, dict) or existing_journal.get("schemaVersion") != 1:
                raise ValueError(f"schemaVersion incompativel em {journal_file}")
            jid = (existing_journal.get("container") or {}).get("id")
            if jid and jid != info["id"]:
                raise ValueError(f"ID divergente para keyring: registrado {jid}, atual {info['id']}")

        if isinstance(existing_journal, dict) and existing_journal.get("phase") != "rolled_back":
            prior_unit = existing_journal.get("prior_unit", {
                "file": str(unit_file),
                "existed": unit_existed,
                "enabled": unit_enabled,
                "active": unit_active,
            })
            prior_dropin = existing_journal.get("prior_dropin", {
                "exists": dropin_exists,
                "is_project_owned": dropin_ours,
            })
            orig_c = existing_journal.get("container") or {}
            if isinstance(orig_c, dict):
                if "prior_restart_policy" in orig_c:
                    info["prior_restart_policy"] = orig_c["prior_restart_policy"]
                if "prior_state" in orig_c:
                    info["prior_state"] = orig_c["prior_state"]
        else:
            prior_unit = {
                "file": str(unit_file),
                "existed": unit_existed,
                "enabled": unit_enabled,
                "active": unit_active,
            }
            prior_dropin = {
                "exists": dropin_exists,
                "is_project_owned": dropin_ours,
            }

        inventory = {
            "schemaVersion": 1,
            "component": "keyring",
            "container": info,
            "prior_unit": prior_unit,
            "prior_dropin": prior_dropin,
            "phase": "inventory",
        }

        if not apply:
            return {
                "status": "dry_run",
                "component": "keyring",
                "inventory": inventory,
            }

        journal = dict(inventory)
        _atomic_write_text(journal_file, json.dumps(journal, indent=2))

        try:
            helper_path = _ensure_launcher_script(state_path)
            rendered = _render_keyring_unit(c_name, helper_path)
            _atomic_write_text(unit_file, rendered)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            journal["phase"] = "units_prepared"
            _atomic_write_text(journal_file, json.dumps(journal, indent=2))

            fresh_info = _inspect_keyring_container_info(c_name)
            if fresh_info["id"] != info["id"]:
                raise ValueError(f"ID divergente para keyring: esperado {info['id']}, atual {fresh_info['id']}")

            podman.run("update", "--restart=no", str(info["id"]))
            journal["phase"] = "policies_updated"
            _atomic_write_text(journal_file, json.dumps(journal, indent=2))

            subprocess.run(["systemctl", "--user", "enable", unit_name], check=True)
            subprocess.run(["systemctl", "--user", "start", unit_name], check=True)
            journal["phase"] = "supervision_started"
            _atomic_write_text(journal_file, json.dumps(journal, indent=2))

            res_act = subprocess.run(["systemctl", "--user", "is-active", unit_name], capture_output=True, text=True)
            if res_act.stdout.strip() != "active":
                raise RuntimeError(f"unidade {unit_name} nao esta ativa apos start: {res_act.stdout.strip()}")

            if dropin_exists and dropin_ours:
                remove_project_dropin(target_path)
                journal["prior_dropin"]["removed_by_adoption"] = True

            journal["phase"] = "readiness_verified"
            _atomic_write_text(journal_file, json.dumps(journal, indent=2))

            return {
                "status": "applied",
                "component": "keyring",
                "phase": journal["phase"],
                "inventory": inventory,
            }

        except Exception as exc:
            journal["error"] = {"type": type(exc).__name__, "message": str(exc)}
            _atomic_write_text(journal_file, json.dumps(journal, indent=2))
            _rollback_keyring_from_journal(journal, target_path)
            raise


def rollback_keyring(
    *,
    target_dir: Path | None = None,
    state_dir: Path | None = None,
) -> dict[str, object]:
    """Reverte supervisão systemd do keyring para legado sem recriar containers."""
    state_path, target_path = _resolve_paths("", target_dir, state_dir)
    lock_path = state_path / ".keyring-adopt.lock"
    c_name = os.environ.get("ASB_KEYRING_CONTAINER", "asb-keyring")

    with _AdoptionLock(lock_path, "keyring"):
        journal_file = state_path / "keyring-journal.json"
        if not journal_file.is_file():
            raise FileNotFoundError(f"diario de keyring ausente em {journal_file}: impossivel determinar estado anterior para rollback")

        try:
            journal = json.loads(journal_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"diario de keyring corrompido: {exc}") from exc

        if not isinstance(journal, dict) or journal.get("schemaVersion") != 1:
            raise ValueError(f"schemaVersion incompativel em {journal_file}")

        fresh_info = _inspect_keyring_container_info(c_name)
        jid = (journal.get("container") or {}).get("id")
        if jid and jid != fresh_info["id"]:
            raise ValueError(f"ID divergente para keyring: registrado {jid}, atual {fresh_info['id']}")

        _rollback_keyring_from_journal(journal, target_path)
        journal["phase"] = "rolled_back"
        _atomic_write_text(journal_file, json.dumps(journal, indent=2))

        return {"status": "rolled_back", "component": "keyring"}
