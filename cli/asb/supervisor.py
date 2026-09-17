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
    "NETWORK_UNIT",
    "NETWORK_UNIT_NAME",
    "network_unit_name",
    "unit_dir",
    "render_unit",
    "render_target",
    "render_network_unit",
    "install_runtime",
    "install_workspace",
    "start_workspace",
    "stop_workspace",
    "remove_workspace_units",
    "escape_systemd_arg",
    "keyring_container_name",
    "keyring_unit_name",
    "render_keyring_unit",
    "install_keyring_unit",
]


def _validate_safe_name(name: str, kind: str = "resource") -> str:
    """Valida estritamente nomes de recursos e unidades rejeitando delimitadores e traversal."""
    if not isinstance(name, str) or not name:
        raise ValueError(f"Nome de {kind} ausente ou vazio: {name!r}")
    if any(c in name for c in ("/", "\\", "..", " ", "\t", "\n", "\r", "\0")):
        raise ValueError(f"Nome de {kind} contem caracteres proibidos ou traversal: {name!r}")
    return name


NETWORK_UNIT = "asb-network.service"
NETWORK_UNIT_NAME = NETWORK_UNIT


def network_unit_name() -> str:
    """Nome da espera por rede; `ASB_NETWORK_UNIT` isola testes de integracao."""
    return os.environ.get("ASB_NETWORK_UNIT") or NETWORK_UNIT


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
    wants_proxy: bool = True
    keyring_unit: str | None = "asb-keyring.service"
    network_unit: str | None = NETWORK_UNIT

    def __post_init__(self) -> None:
        for field_name in ("name", "container_id", "role", "unit_name", "target_name"):
            val = getattr(self, field_name)
            if not isinstance(val, str):
                raise TypeError(f"{field_name} must be a string, got {type(val).__name__}")
            _validate_safe_name(val, field_name)

        if self.keyring_unit is not None:
            if not isinstance(self.keyring_unit, str):
                raise TypeError(f"keyring_unit must be a string or None, got {type(self.keyring_unit).__name__}")
            _validate_safe_name(self.keyring_unit, "keyring_unit")

        if self.network_unit is not None:
            if not isinstance(self.network_unit, str):
                raise TypeError(f"network_unit must be a string or None, got {type(self.network_unit).__name__}")
            _validate_safe_name(self.network_unit, "network_unit")

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
        keyring_deps = (unit.keyring_unit,) if unit.keyring_unit else ()
        after_deps = tuple(dict.fromkeys((proxy_unit,) + keyring_deps + unit.extra_after))
        wants_list = list(keyring_deps)
        if unit.wants_proxy:
            wants_list.insert(0, proxy_unit)
        wants_deps = tuple(dict.fromkeys(tuple(wants_list) + unit.extra_wants))
    else:
        after_deps = unit.extra_after
        wants_deps = unit.extra_wants

    # Emenda A §3: toda unidade de container espera a conectividade real do
    # host. Qualquer container bridge que partisse antes criaria o namespace
    # rootless cedo, sem egresso, e nada a jusante o repararia.
    network_deps = (unit.network_unit,) if unit.network_unit else ()
    after_deps = tuple(dict.fromkeys(network_deps + tuple(after_deps)))
    requires_line = f"Requires={' '.join(network_deps)}\n" if network_deps else ""

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
        f"{requires_line}"
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


def render_network_unit(gate_path: Path, target: str | None = None) -> str:
    """Renderiza a espera unica por conectividade real (Emenda A §4).

    `TimeoutStartSec=infinity`: sem rede, os workspaces aguardam e sobem
    sozinhos quando ela chegar. `Restart=on-failure` cobre so falha do proprio
    script; ausencia de rede nao e falha. Sem `[Install]`: quem a puxa sao as
    unidades de workspace, por `Requires=`.
    """
    gate_escaped = escape_systemd_arg(gate_path)
    env_line = (
        f"Environment=ASB_NETWORK_GATE_TARGET={escape_systemd_arg(target)}\n"
        if target else ""
    )
    return (
        "[Unit]\n"
        "Description=Agent Sandbox: espera por conectividade real\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        "TimeoutStartSec=infinity\n"
        "Restart=on-failure\n"
        "RestartSec=5s\n"
        f"{env_line}"
        f"ExecStart={gate_escaped}\n"
    )


def _atomic_write_text(path: Path, content: str, mode: int | None = None) -> None:
    """Grava conteúdo (e, se informado, modo) de forma atômica no caminho de destino."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp.{os.getpid()}"
    try:
        tmp_path.write_text(content, encoding="utf-8")
        if mode is not None:
            tmp_path.chmod(mode)
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _resolve_paths(
    ws: str = "",
    target_dir: Path | None = None,
    state_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Resolve state_path e target_path.

    ASB_STATE_ROOT relocaliza o estado e ASB_SYSTEMD_UNIT_DIR relocaliza as
    units. ASB_CONFIG_ROOT NAO e raiz de units: o manager systemd --user nao
    le esse diretorio (medido com `systemd-analyze --user unit-paths`), e units
    gravadas ali seriam ignoradas. Uma raiz fora do search path do manager e
    recusada por _require_manager_reads() antes de qualquer escrita.
    """
    if ws:
        _validate_safe_name(ws, "workspace")
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
        state_path = state_base / "keyring"

    if target_dir is not None:
        target_path = target_dir
    elif "ASB_SYSTEMD_UNIT_DIR" in os.environ:
        target_path = Path(os.environ["ASB_SYSTEMD_UNIT_DIR"])
    else:
        target_path = Path.home() / ".config" / "systemd" / "user"
    return state_path, target_path


def unit_dir(ws: str = "", target_dir: Path | None = None,
             state_dir: Path | None = None) -> Path:
    """Diretorio onde as unidades deste manager vivem (respeita as variaveis
    de isolamento da suite)."""
    return _resolve_paths(ws, target_dir, state_dir)[1]


def install_workspace(
    ws: str,
    target_dir: Path | None = None,
    state_dir: Path | None = None,
    helper_path: Path | None = None,
) -> list[Path]:
    """Instala as unidades systemd do workspace e executa daemon-reload."""
    _validate_safe_name(ws, "workspace")

    state_path, target_path = _resolve_paths(ws, target_dir, state_dir)
    manifest_file = state_path / "runtime.json"
    if not manifest_file.is_file():
        raise FileNotFoundError(f"Manifesto de runtime nao encontrado em: {manifest_file}")

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Falha ao ler manifesto {manifest_file}: {exc}") from exc

    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ValueError(f"Manifesto invalido em {manifest_file}: esperado schemaVersion 1")

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

    # Espera unica por rede, compartilhada por todo workspace. Fica FORA de
    # `written_files`: essa lista alimenta o rollback transacional do `up`, e
    # a falha de um workspace nunca pode apagar a espera dos outros.
    gate_path = (
        helper_path / "network_gate.py"
        if helper_path.is_dir()
        else helper_path.parent / "network_gate.py"
    )
    network_unit = network_unit_name()
    _atomic_write_text(
        target_path / network_unit,
        render_network_unit(gate_path, target=os.environ.get("ASB_NETWORK_GATE_TARGET") or None),
    )

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
            network_unit=network_unit,
            keyring_unit=keyring_unit_name(),
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
    state_path, target_path = _resolve_paths(ws, target_dir, state_dir)

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
    # Um symlink de wants que sobra reabilita o target no proximo boot: so a
    # ausencia e tolerada, qualquer outra falha propaga.
    (target_path / "default.target.wants" / target).unlink(missing_ok=True)

    # Coletar nomes EXATOS de unidade de servico a partir do manifesto do
    # proprio workspace. Sem manifesto (ou sem containers validos), nao ha
    # como saber quais nomes pertencem a este workspace — nada e removido
    # por adivinhacao/glob.
    unit_names: list[str] = []
    manifest_file = state_path / "runtime.json"
    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"manifesto de runtime corrompido: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ValueError("manifesto de runtime corrompido: raiz deve ser um objeto JSON")
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


def keyring_container_name() -> str:
    """Container do keyring singleton; `ASB_KEYRING_CONTAINER` isola testes."""
    return os.environ.get("ASB_KEYRING_CONTAINER", "asb-keyring")


def keyring_unit_name() -> str:
    """Unidade do keyring, nomeada pelo container como `asb-{ws}-{role}.service`."""
    return f"{keyring_container_name()}.service"


def render_keyring_unit(c_name: str, runtime_dir: Path) -> str:
    """Renderiza a unidade Type=exec do keyring singleton (Emenda A §5).

    `ExecStartPost` so deixa a unidade ativa com o Secret Service respondendo,
    entao o `After=` do agente espera o D-Bus pronto, nao so o processo. O
    container roda com `--network none`: a unidade NAO depende da espera por
    rede.
    """
    _validate_safe_name(c_name, "keyring_container")
    launcher = escape_systemd_arg(runtime_dir / "launcher.sh")
    check = escape_systemd_arg(runtime_dir / "runtime_check.py")
    name_escaped = escape_systemd_arg(c_name)
    podman_escaped = escape_systemd_arg(shutil.which("podman") or "/usr/bin/podman")

    env_lines = ""
    for var in (
        "ASB_CREDENTIALS_VOLUME",
        "ASB_KEYRING_DATA_VOLUME",
        "ASB_KEYRING_RUNTIME_VOLUME",
        "ASB_KEYRING_PASS_FILE",
    ):
        val = os.environ.get(var)
        if val:
            env_lines += f"Environment={escape_systemd_arg(f'{var}={val}')}\n"

    return (
        "[Unit]\n"
        "Description=Agent Sandbox Secret Service keyring singleton\n"
        "StartLimitIntervalSec=600s\n"
        "StartLimitBurst=3\n"
        "\n"
        "[Service]\n"
        f"{env_lines}"
        "Type=exec\n"
        f"ExecStart={launcher} start --attach --sig-proxy=false {name_escaped}\n"
        f"ExecStartPost={check} --role keyring --container {name_escaped}\n"
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


def install_keyring_unit(
    c_name: str,
    runtime_dir: Path,
    target_dir: Path | None = None,
) -> Path:
    """Grava a unidade do keyring atomicamente e executa daemon-reload."""
    _, target_path = _resolve_paths("", target_dir, None)
    target_path.mkdir(parents=True, exist_ok=True)
    unit_file = target_path / f"{c_name}.service"
    _atomic_write_text(unit_file, render_keyring_unit(c_name, runtime_dir))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    return unit_file
