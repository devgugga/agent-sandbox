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

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

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
    if unit.role in ("proxy", "agent"):
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
