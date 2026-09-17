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
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import install, podman
from .install import (
    get_dropin_path,
    install_runtime,
    remove_project_dropin,
    restore_project_dropin,
)

__all__ = [
    "ContainerUnit",
    "NETWORK_UNIT",
    "NETWORK_UNIT_NAME",
    "network_unit_name",
    "render_unit",
    "render_target",
    "render_network_unit",
    "install_network_unit",
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


def install_network_unit(
    target_dir: Path,
    gate_path: Path,
    target: str | None = None,
) -> Path:
    """Instala a unidade de espera por conectividade real (Emenda A §4)."""
    network_unit = network_unit_name()
    unit_path = target_dir / network_unit
    _atomic_write_text(
        unit_path,
        render_network_unit(gate_path, target=target),
    )
    return unit_path


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


class _AdoptionLock:
    """flock exclusivo e nao-bloqueante sobre o proprio diretorio de estado.

    O objeto travado e o diretorio, nao um arquivo dentro dele: assim o
    dry-run disputa o mesmo lock que apply e rollback sem criar arquivo algum.
    Com `create=False` (dry-run e rollback) o diretorio nao e criado; se ele
    nao existe, nao ha diario nem baseline persistido a proteger e nada e
    travado. Disputa resulta em recusa imediata (fail-closed, sem esperar).
    """

    def __init__(self, state_dir: Path, component_name: str, *, create: bool) -> None:
        self.state_dir = state_dir
        self.component_name = component_name
        self.create = create
        self.fd: int | None = None

    def __enter__(self) -> _AdoptionLock:
        if self.create:
            self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.state_dir, os.O_RDONLY | os.O_DIRECTORY)
        except FileNotFoundError:
            if self.create:
                raise
            return self
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self.fd)
            self.fd = None
            raise RuntimeError(
                f"lock ocupado ({self.state_dir}): outro processo esta operando '{self.component_name}'"
            ) from exc
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.fd is not None:
            os.close(self.fd)  # fechar o descritor libera o flock
            self.fd = None


# Pares (exit code, stdout) aceitos de `systemctl --user is-enabled/is-active`,
# medidos contra systemd 261. Qualquer outro par falha fechado — estados que a
# adocao nao sabe restaurar (masked, linked, alias, generated, transient, bad,
# indirect, maintenance) — e qualquer stderr, mesmo com um stdout conhecido.
# Estados transitorios (uma unit com Restart=always cujo ExecStartPost falhou
# fica `activating` em auto-restart) so sao aceitos para PARAR a unit: como
# baseline ou pos-condicao eles falham fechado (_systemd_unit_status).
_ENABLE_STATES = {(0, "enabled"), (0, "enabled-runtime"), (0, "static"), (1, "disabled"), (4, "not-found")}
_ACTIVE_STATES = {
    (0, "active"), (3, "inactive"), (3, "failed"), (4, "inactive"),
    (3, "activating"), (3, "deactivating"), (0, "reloading"),
}
_TRANSITIONAL = ("activating", "deactivating", "reloading")
_ENABLED = ("enabled", "enabled-runtime")


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    """Consulta ao manager do usuario; quem chama interpreta rc, stdout e stderr."""
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def _unit_state(unit_name: str) -> tuple[str, str]:
    """(estado de habilitacao, estado de atividade), validados contra as tabelas acima."""
    _validate_safe_name(unit_name, "unit_name")
    states = []
    for verb, table in (("is-enabled", _ENABLE_STATES), ("is-active", _ACTIVE_STATES)):
        res = _systemctl(verb, unit_name)
        out, err = res.stdout.strip(), res.stderr.strip()
        if err or (res.returncode, out) not in table:
            raise RuntimeError(
                f"{verb} {unit_name} retornou estado nao suportado "
                f"(rc={res.returncode}, stdout={out!r}, stderr={err!r})"
            )
        states.append(out)
    return states[0], states[1]


def _systemd_unit_status(unit_name: str) -> tuple[bool, bool]:
    """Retorna (habilitada, ativa); estado transitorio nao e baseline valido."""
    enabled, active = _unit_state(unit_name)
    if active in _TRANSITIONAL:
        raise RuntimeError(f"{unit_name} em estado transitorio '{active}': nao ha baseline confiavel")
    return enabled in _ENABLED, active == "active"


def _inspect_container_restart_policy(cid: str) -> tuple[str, int]:
    """Inspeciona a política de restart e o retry count do container."""
    raw = podman.out("container", "inspect", cid, "--format", "{{json .HostConfig.RestartPolicy}}")
    data = json.loads(raw)
    name = str(data.get("Name", "") or "")
    retry = int(data.get("MaximumRetryCount", 0) or 0)
    return name, retry


def _format_restart_policy_arg(policy_name: str, retry_count: int = 0) -> str:
    """Formata o argumento --restart para o comando podman update."""
    if policy_name == "on-failure" and retry_count > 0:
        return f"--restart=on-failure:{retry_count}"
    return f"--restart={policy_name}"


def _current_revision(root: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        # Falha do git nao vira "dev": gravado no runtime.json de uma adocao
        # interrompida, faria a retomada (git de volta) recusar a fase.
        detail = (getattr(exc, "stderr", None) or str(exc)).strip()
        raise RuntimeError(f"revisao do checkout {root} indisponivel: {detail}") from exc
    rev = res.stdout.strip()
    if not rev or any(c in rev for c in ("/", "\\", "..", " ", "\t", "\n", "\r")):
        raise RuntimeError(f"revisao do checkout {root} invalida: {rev!r}")
    return rev


def _validate_installed_runtime(dest: Path, expected: dict[str, object]) -> bool:
    """Confere o runtime em `dest` contra um manifesto esperado vindo de FORA de `dest`.

    `expected` e derivado do checkout (install.runtime_manifest) ou fornecido
    pelo chamador que montou o runtime. O manifest.json adjacente tem de ser
    identico a ele e cada arquivo tem de bater em hash e modo: adulterar
    payload e manifesto juntos nao cria uma nova raiz de confianca.
    """
    try:
        manifest_file = dest / "manifest.json"
        if dest.is_symlink() or manifest_file.is_symlink() or not manifest_file.is_file():
            return False
        if json.loads(manifest_file.read_text(encoding="utf-8")) != expected:
            return False
        files = expected.get("files")
        if not isinstance(files, dict) or not all(k in files for k in ("launcher.sh", "runtime_check.py", "asb/__init__.py")):
            return False
        actual: set[str] = set()
        for p in dest.rglob("*"):
            if p.is_symlink():
                return False
            if p.is_file() and p != manifest_file:
                actual.add(p.relative_to(dest).as_posix())
        if actual != set(files):
            return False
        for rel, info in files.items():
            path = dest / rel
            if not isinstance(info, dict) or hashlib.sha256(path.read_bytes()).hexdigest() != info.get("sha256"):
                return False
            if path.stat().st_mode & 0o777 != info.get("mode"):
                return False
        return True
    except (OSError, ValueError):
        return False


def _resolve_versioned_runtime(
    helper_path: Path | None = None,
    runtime_manifest: dict[str, object] | None = None,
    revision: str | None = None,
    target_base: Path | None = None,
    root: Path | None = None,
) -> tuple[Path, Path, str]:
    """Retorna (launcher, runtime_check, revisao) de um runtime integro.

    Sem helper_path: runtime versionado derivado do checkout, reinstalado se
    divergir do conjunto esperado. Com helper_path: runtime montado pelo
    chamador, que TEM de informar o manifesto esperado (`runtime_manifest`);
    helper_path tem de ser o launcher.sh desse runtime, nao qualquer irmao.
    """
    if helper_path is not None:
        if runtime_manifest is None:
            raise ValueError("helper_path exige runtime_manifest: o manifesto adjacente nao autentica o runtime")
        if helper_path.name != "launcher.sh":
            raise ValueError(f"helper_path deve ser o launcher.sh do runtime, obteve {helper_path.name!r}")
        dest = helper_path.parent
        if not _validate_installed_runtime(dest, runtime_manifest):
            raise RuntimeError(f"falha de integridade do runtime em {dest} contra o manifesto esperado")
        return helper_path, dest / "runtime_check.py", str(runtime_manifest.get("revision"))

    checkout_root = root or Path(__file__).resolve().parent.parent.parent
    rev = revision or _current_revision(checkout_root)
    expected = install.runtime_manifest(checkout_root, rev)
    base = target_base or (Path.home() / ".local" / "lib" / "agent-sandbox" / "runtime")
    dest = base / rev
    if not _validate_installed_runtime(dest, expected):
        install_runtime(checkout_root, rev, target_base=base)
        if not _validate_installed_runtime(dest, expected):
            raise RuntimeError(f"falha de integridade ao validar runtime instalado em {dest}")
    return dest / "launcher.sh", dest / "runtime_check.py", rev


def _verify_unit_files(unit_paths: list[Path], target_dir: Path | None = None) -> None:
    """Valida a sintaxe e integridade das unidades com systemd-analyze --user verify."""
    env = os.environ.copy()
    if target_dir is not None:
        user_unit_dir = Path.home() / ".config" / "systemd" / "user"
        existing_path = env.get("SYSTEMD_UNIT_PATH", "")
        if existing_path:
            env["SYSTEMD_UNIT_PATH"] = f"{target_dir}:{user_unit_dir}:{existing_path}"
        else:
            env["SYSTEMD_UNIT_PATH"] = f"{target_dir}:{user_unit_dir}:"
    cmd = ["systemd-analyze", "--user", "verify"] + [str(p) for p in unit_paths]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        raise RuntimeError(
            f"systemd-analyze verify falhou (rc={res.returncode}): {res.stderr.strip() or res.stdout.strip()}"
        )


CANONICAL_ROLES = ("agent", "proxy", "forwarder", "docker")
VALID_PHASES = {
    "inventory",
    "units_prepared",
    "policies_updated",
    "supervision_started",
    "readiness_verified",
    "supervision_configured",
    "rolled_back",
}


def _inspect_workspace_containers(ws: str) -> dict[str, dict[str, object]]:
    """Inventaria estritamente containers pertencentes ao workspace pelo label exato."""
    if not ws or any(c in ws for c in ("/", "\\", "..", " ", "\t", "\n", "\r")):
        raise ValueError(f"Nome de workspace invalido: {ws!r}")

    names_raw = podman.out("ps", "-a", "--filter", f"label=asb.workspace={ws}", "--format", "{{.Names}}")
    names = [n.strip() for n in names_raw.splitlines() if n.strip()]
    if not names:
        raise ValueError(f"nenhum container encontrado para o workspace '{ws}'")

    containers: dict[str, dict[str, object]] = {}
    for name in names:
        if "\n" in name or "\r" in name or "/" in name or "\\" in name:
            raise ValueError(f"Nome de container invalido ou inseguro: {name!r}")

        raw = podman.out("container", "inspect", name, "--format", "{{json .}}")
        data = json.loads(raw)
        cid = str(data.get("Id", "")).strip()
        if not cid or any(c in cid for c in ("/", "\\", "..", " ", "\t", "\n", "\r")):
            raise ValueError(f"ID de container invalido ou vazio para '{name}': {cid!r}")

        cfg = data.get("Config", {})
        labels = cfg.get("Labels", {}) or {}
        role = labels.get("asb.role") or ""
        if role == "pilot":
            role = "agent"

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
                raise ValueError(f"impossivel determinar papel canonico para o container '{name}'")

        if role not in CANONICAL_ROLES or any(c in role for c in ("/", "\\", "..", " ", "\t", "\n", "\r")):
            raise ValueError(f"papel nao-canonico ou invalido '{role}' no container '{name}'")

        if role in containers:
            raise ValueError(
                f"papel duplicado '{role}' detectado: '{name}' e '{containers[role]['name']}'"
            )

        state = data.get("State", {})
        status = "running" if state.get("Running") else (state.get("Status") or "stopped")
        host_cfg = data.get("HostConfig", {})
        restart_obj = host_cfg.get("RestartPolicy", {}) or {}
        policy = restart_obj.get("Name") or "unless-stopped"
        retry_count = int(restart_obj.get("MaximumRetryCount") or 0)
        image = cfg.get("Image", "")

        mounts = [
            {"source": m.get("Source"), "destination": m.get("Destination"), "type": m.get("Type")}
            for m in data.get("Mounts", [])
            if isinstance(m, dict)
        ]

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
            "prior_retry_count": retry_count,
            "mounts": mounts,
            "ports": ports,
            "unit_name": unit_name,
        }
    return containers


def _validate_typed_error(err_obj: object, field_name: str) -> None:
    """Valida a estrutura tipada dos campos error e rollback_error no diario."""
    if not isinstance(err_obj, dict):
        raise ValueError(f"campo {field_name!r} no diario deve ser um dicionario")
    allowed_err_keys = {"type", "message", "phase", "timestamp"}
    if set(err_obj.keys()) != allowed_err_keys:
        diff = set(err_obj.keys()) ^ allowed_err_keys
        raise ValueError(f"chaves invalidas ou ausentes em {field_name!r}: {sorted(diff)}")
    for k in allowed_err_keys:
        val = err_obj.get(k)
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"campo {k!r} em {field_name!r} deve ser string nao-vazia")


def _validate_journal_structure(
    journal: dict[str, object],
    expected_component: str,
    ws: str = "",
    expected_unit_name: str | None = None,
    target_path: Path | None = None,
    state_path: Path | None = None,
) -> None:
    """Valida estruturalmente o diário (schemaVersion, tipos, chaves obrigatórias, IDs não vazios)."""
    expected_unit_name = expected_unit_name or _keyring_unit_name()
    if not isinstance(journal, dict):
        raise ValueError("diario invalido: esperado objeto JSON")

    if journal.get("schemaVersion") != 1:
        raise ValueError(f"schemaVersion incompativel: esperado 1, obteve {journal.get('schemaVersion')}")

    phase = journal.get("phase")
    if phase not in VALID_PHASES:
        raise ValueError(f"fase desconhecida ou invalida no diario: {phase!r}")

    if expected_component == "workspace":
        allowed_keys = {
            "schemaVersion",
            "workspace",
            "containers",
            "prior_units",
            "runtime_manifest_baseline",
            "diagnostics",
            "phase",
            "error",
            "rollback_error",
        }
        required_keys = {
            "schemaVersion",
            "workspace",
            "containers",
            "prior_units",
            "runtime_manifest_baseline",
            "diagnostics",
            "phase",
        }
        extra_keys = set(journal.keys()) - allowed_keys
        if extra_keys:
            raise ValueError(f"chaves nao reconhecidas no diario: {sorted(extra_keys)}")
        missing_keys = required_keys - set(journal.keys())
        if missing_keys:
            raise ValueError(f"chaves obrigatorias ausentes no diario: {sorted(missing_keys)}")

        j_ws = journal.get("workspace")
        if not isinstance(j_ws, str) or not j_ws or any(c in j_ws for c in ("/", "\\", "..", " ", "\t", "\n", "\r")):
            raise ValueError(f"workspace invalido no diario: {j_ws!r}")
        if ws and j_ws != ws:
            raise ValueError(f"workspace incompativel no diario: esperado {ws!r}, obteve {j_ws!r}")

        containers = journal.get("containers")
        if not isinstance(containers, dict) or not containers:
            raise ValueError("diario invalido: campo 'containers' deve ser um dicionario nao-vazio")

        allowed_c_keys = {
            "id", "name", "role", "image", "prior_state",
            "prior_restart_policy", "prior_retry_count", "mounts", "ports", "unit_name"
        }
        for role, c in containers.items():
            if role not in CANONICAL_ROLES:
                raise ValueError(f"papel nao-canonico no diario: {role!r}")
            if not isinstance(c, dict):
                raise ValueError(f"entrada do container '{role}' no diario deve ser um dicionario")
            if set(c.keys()) != allowed_c_keys:
                diff = set(c.keys()) ^ allowed_c_keys
                raise ValueError(f"chaves invalidas ou ausentes para container '{role}': {sorted(diff)}")
            if c.get("role") != role:
                raise ValueError(f"role divergente para '{role}': {c.get('role')!r}")
            cid = c.get("id")
            if not isinstance(cid, str) or not cid.strip() or any(ch in cid for ch in ("/", "\\", "..", " ", "\t", "\n", "\r")):
                raise ValueError(f"ID ausente, vazio ou invalido para container '{role}' no diario: {cid!r}")
            cname = c.get("name")
            if not isinstance(cname, str) or not cname or any(ch in cname for ch in ("/", "\\", "..", " ", "\t", "\n", "\r")):
                raise ValueError(f"nome ausente, vazio ou invalido para container '{role}' no diario: {cname!r}")
            pol = c.get("prior_restart_policy")
            if pol not in ("unless-stopped", "always", "no", "on-failure"):
                raise ValueError(f"prior_restart_policy invalida para '{role}': {pol!r}")
            retry = c.get("prior_retry_count")
            if not isinstance(retry, int) or retry < 0:
                raise ValueError(f"prior_retry_count invalido para '{role}': {retry!r}")
            st = c.get("prior_state")
            if st not in ("running", "stopped", "created", "exited"):
                raise ValueError(f"prior_state invalido para '{role}': {st!r}")
            u_expected = f"asb-{j_ws}-{role}.service"
            if c.get("unit_name") != u_expected:
                raise ValueError(f"unit_name invalido para container '{role}': esperado {u_expected}, obteve {c.get('unit_name')!r}")
            mounts = c.get("mounts")
            if not isinstance(mounts, list):
                raise ValueError(f"mounts de '{role}' deve ser lista")
            for m in mounts:
                if not isinstance(m, dict) or set(m.keys()) != {"source", "destination", "type"}:
                    raise ValueError(f"mount invalido no container '{role}': {m!r}")
            ports = c.get("ports")
            if not isinstance(ports, list):
                raise ValueError(f"ports de '{role}' deve ser lista")
            for p in ports:
                if not isinstance(p, dict) or set(p.keys()) != {"container_port", "host_port"}:
                    raise ValueError(f"port invalido no container '{role}': {p!r}")

        any_running = any(c.get("prior_state") == "running" for c in containers.values())
        all_stopped = not any_running
        if phase == "supervision_configured" and any_running:
            raise ValueError("fase 'supervision_configured' incoerente: containers tinham prior_state='running'")
        if phase in ("supervision_started", "readiness_verified") and all_stopped:
            raise ValueError("fase incoerente: todos containers tinham prior_state='stopped'")

        prior_units = journal.get("prior_units")
        if not isinstance(prior_units, dict):
            raise ValueError("diario invalido: campo 'prior_units' ausente ou invalido")
        allowed_pu_keys = {
            "target_file", "target_existed", "target_content", "target_mode",
            "target_enabled", "target_active", "services"
        }
        if set(prior_units.keys()) != allowed_pu_keys:
            diff = set(prior_units.keys()) ^ allowed_pu_keys
            raise ValueError(f"chaves invalidas ou ausentes em prior_units: {sorted(diff)}")

        target_file = prior_units.get("target_file")
        if (
            not isinstance(target_file, str)
            or not target_file.startswith("/")
            or ".." in target_file
            or "\\" in target_file
            or Path(target_file).name != f"asb-{j_ws}.target"
        ):
            raise ValueError(f"target_file invalido ou com traversal em prior_units: {target_file!r}")
        if target_path is not None:
            expected_target_file = str(target_path / f"asb-{j_ws}.target")
            if target_file != expected_target_file:
                raise ValueError(f"caminho de target_file nao derivado das raizes canonicas: esperado {expected_target_file}, obteve {target_file}")
        t_existed = prior_units.get("target_existed")
        if not isinstance(t_existed, bool):
            raise ValueError("target_existed deve ser booleano")
        if t_existed:
            if not isinstance(prior_units.get("target_content"), str):
                raise ValueError("target_content deve ser string quando target_existed=True")
            if not isinstance(prior_units.get("target_mode"), int):
                raise ValueError("target_mode deve ser int quando target_existed=True")
        else:
            if prior_units.get("target_content") is not None:
                raise ValueError("target_content deve ser None quando target_existed=False")
            if prior_units.get("target_mode") is not None:
                raise ValueError("target_mode deve ser None quando target_existed=False")

        if not isinstance(prior_units.get("target_enabled"), bool):
            raise ValueError("target_enabled deve ser booleano")
        if not isinstance(prior_units.get("target_active"), bool):
            raise ValueError("target_active deve ser booleano")

        services = prior_units.get("services")
        if not isinstance(services, dict):
            raise ValueError("campo 'services' em prior_units deve ser um dicionario")

        valid_unit_names = {f"asb-{j_ws}-{r}.service" for r in containers.keys()}
        if set(services.keys()) != valid_unit_names:
            raise ValueError(
                f"conjunto de services diverge dos roles dos containers: "
                f"esperado {sorted(valid_unit_names)}, obteve {sorted(services.keys())}"
            )

        allowed_si_keys = {"file", "existed", "content", "mode", "enabled", "active"}
        for u_key, s_info in services.items():
            if not isinstance(s_info, dict):
                raise ValueError(f"detalhes de '{u_key}' em prior_units devem ser um dicionario")
            if set(s_info.keys()) != allowed_si_keys:
                diff = set(s_info.keys()) ^ allowed_si_keys
                raise ValueError(f"chaves invalidas ou ausentes em servico '{u_key}': {sorted(diff)}")
            s_file = s_info.get("file")
            if (
                not isinstance(s_file, str)
                or not s_file.startswith("/")
                or ".." in s_file
                or "\\" in s_file
                or Path(s_file).name != u_key
            ):
                raise ValueError(f"file invalido ou com traversal em '{u_key}': {s_file!r}")
            if target_path is not None:
                expected_svc_file = str(target_path / u_key)
                if s_file != expected_svc_file:
                    raise ValueError(f"caminho de service file '{u_key}' nao derivado das raizes canonicas: esperado {expected_svc_file}, obteve {s_file}")
            s_existed = s_info.get("existed")
            if not isinstance(s_existed, bool):
                raise ValueError(f"'existed' de '{u_key}' deve ser booleano")
            if s_existed:
                if not isinstance(s_info.get("content"), str):
                    raise ValueError(f"'content' de '{u_key}' deve ser string quando existed=True")
                if not isinstance(s_info.get("mode"), int):
                    raise ValueError(f"'mode' de '{u_key}' deve ser int quando existed=True")
            else:
                if s_info.get("content") is not None:
                    raise ValueError(f"'content' de '{u_key}' deve ser None quando existed=False")
                if s_info.get("mode") is not None:
                    raise ValueError(f"'mode' de '{u_key}' deve ser None quando existed=False")
            if not isinstance(s_info.get("enabled"), bool):
                raise ValueError(f"'enabled' de '{u_key}' deve ser booleano")
            if not isinstance(s_info.get("active"), bool):
                raise ValueError(f"'active' de '{u_key}' deve ser booleano")

        manifest_baseline = journal.get("runtime_manifest_baseline")
        if not isinstance(manifest_baseline, dict):
            raise ValueError("campo 'runtime_manifest_baseline' ausente ou invalido no diario")
        allowed_mb_keys = {"file", "existed", "content", "mode"}
        if set(manifest_baseline.keys()) != allowed_mb_keys:
            diff = set(manifest_baseline.keys()) ^ allowed_mb_keys
            raise ValueError(f"chaves invalidas ou ausentes em runtime_manifest_baseline: {sorted(diff)}")
        m_file = manifest_baseline.get("file")
        if (
            not isinstance(m_file, str)
            or not m_file.startswith("/")
            or ".." in m_file
            or "\\" in m_file
            or Path(m_file).name != "runtime.json"
        ):
            raise ValueError(f"arquivo de runtime_manifest_baseline invalido: {m_file!r}")
        if state_path is not None:
            expected_m_file = str(state_path / "runtime.json")
            if m_file != expected_m_file:
                raise ValueError(f"caminho de runtime_manifest_baseline nao derivado das raizes canonicas: esperado {expected_m_file}, obteve {m_file}")
        mb_existed = manifest_baseline.get("existed")
        if not isinstance(mb_existed, bool):
            raise ValueError("'existed' em runtime_manifest_baseline deve ser booleano")
        if mb_existed:
            if not isinstance(manifest_baseline.get("content"), str):
                raise ValueError("'content' deve ser string quando existed=True em manifest_baseline")
            if not isinstance(manifest_baseline.get("mode"), int):
                raise ValueError("'mode' deve ser int quando existed=True em manifest_baseline")
        else:
            if manifest_baseline.get("content") is not None:
                raise ValueError("'content' deve ser None quando existed=False em manifest_baseline")
            if manifest_baseline.get("mode") is not None:
                raise ValueError("'mode' deve ser None quando existed=False em manifest_baseline")

        diag = journal.get("diagnostics")
        if not isinstance(diag, dict):
            raise ValueError("campo 'diagnostics' ausente ou invalido no diario")
        allowed_diag_keys = {"legacy_credentials_layout", "forwarder_needs_recreation", "rootless_netns_producers"}
        if set(diag.keys()) != allowed_diag_keys:
            diff = set(diag.keys()) ^ allowed_diag_keys
            raise ValueError(f"chaves invalidas ou ausentes em diagnostics: {sorted(diff)}")

        if "error" in journal:
            _validate_typed_error(journal["error"], "error")
        if "rollback_error" in journal:
            _validate_typed_error(journal["rollback_error"], "rollback_error")

    elif expected_component == "keyring":
        allowed_keys = {
            "schemaVersion",
            "component",
            "container",
            "prior_unit",
            "prior_dropin",
            "phase",
            "error",
            "rollback_error",
        }
        required_keys = {
            "schemaVersion",
            "component",
            "container",
            "prior_unit",
            "prior_dropin",
            "phase",
        }
        extra_keys = set(journal.keys()) - allowed_keys
        if extra_keys:
            raise ValueError(f"chaves nao reconhecidas no diario: {sorted(extra_keys)}")
        missing_keys = required_keys - set(journal.keys())
        if missing_keys:
            raise ValueError(f"chaves obrigatorias ausentes no diario: {sorted(missing_keys)}")

        if journal.get("component") != "keyring":
            raise ValueError(f"component incompativel no diario de keyring: {journal.get('component')!r}")

        c = journal.get("container")
        if not isinstance(c, dict):
            raise ValueError("diario de keyring invalido: campo 'container' deve ser um dicionario")
        allowed_kc_keys = {"id", "name", "prior_state", "prior_restart_policy", "prior_retry_count", "image"}
        if set(c.keys()) != allowed_kc_keys:
            diff = set(c.keys()) ^ allowed_kc_keys
            raise ValueError(f"chaves invalidas ou ausentes para container do keyring: {sorted(diff)}")
        cid = c.get("id")
        if not isinstance(cid, str) or not cid.strip() or any(ch in cid for ch in ("/", "\\", "..", " ", "\t", "\n", "\r")):
            raise ValueError(f"ID ausente, vazio ou invalido para keyring no diario: {cid!r}")
        cname = c.get("name")
        if not isinstance(cname, str) or not cname or any(ch in cname for ch in ("/", "\\", "..", " ", "\t", "\n", "\r")):
            raise ValueError(f"nome ausente, vazio ou invalido para keyring no diario: {cname!r}")
        pol = c.get("prior_restart_policy")
        if pol not in ("unless-stopped", "always", "no", "on-failure"):
            raise ValueError(f"prior_restart_policy invalida para keyring: {pol!r}")
        retry = c.get("prior_retry_count")
        if not isinstance(retry, int) or retry < 0:
            raise ValueError(f"prior_retry_count invalido para keyring: {retry!r}")
        st = c.get("prior_state")
        if st not in ("running", "stopped", "created", "exited"):
            raise ValueError(f"prior_state invalido para keyring: {st!r}")

        k_running = (st == "running")
        if phase == "supervision_configured" and k_running:
            raise ValueError("fase 'supervision_configured' incoerente para keyring: prior_state era 'running'")
        if phase in ("supervision_started", "readiness_verified") and not k_running:
            raise ValueError("fase incoerente para keyring: prior_state era 'stopped'")

        prior_unit = journal.get("prior_unit")
        if not isinstance(prior_unit, dict):
            raise ValueError("diario de keyring invalido: campo 'prior_unit' ausente ou invalido")
        allowed_kpu_keys = {"file", "existed", "content", "mode", "enabled", "active"}
        if set(prior_unit.keys()) != allowed_kpu_keys:
            diff = set(prior_unit.keys()) ^ allowed_kpu_keys
            raise ValueError(f"chaves invalidas ou ausentes em prior_unit do keyring: {sorted(diff)}")
        u_file = prior_unit.get("file")
        if (
            not isinstance(u_file, str)
            or not u_file.startswith("/")
            or ".." in u_file
            or "\\" in u_file
            or Path(u_file).name != expected_unit_name
        ):
            raise ValueError(f"arquivo invalido ou com traversal em prior_unit do keyring: {u_file!r}")
        if target_path is not None:
            expected_u_file = str(target_path / expected_unit_name)
            if u_file != expected_u_file:
                raise ValueError(f"caminho de unit file do keyring nao derivado das raizes canonicas: esperado {expected_u_file}, obteve {u_file}")
        u_existed = prior_unit.get("existed")
        if not isinstance(u_existed, bool):
            raise ValueError("'existed' em prior_unit do keyring deve ser booleano")
        if u_existed:
            if not isinstance(prior_unit.get("content"), str):
                raise ValueError("content deve ser string quando existed=True em prior_unit do keyring")
            if not isinstance(prior_unit.get("mode"), int):
                raise ValueError("mode deve ser int quando existed=True em prior_unit do keyring")
        else:
            if prior_unit.get("content") is not None:
                raise ValueError("content deve ser None quando existed=False em prior_unit do keyring")
            if prior_unit.get("mode") is not None:
                raise ValueError("mode deve ser None quando existed=False em prior_unit do keyring")
        if not isinstance(prior_unit.get("enabled"), bool):
            raise ValueError("'enabled' em prior_unit do keyring deve ser booleano")
        if not isinstance(prior_unit.get("active"), bool):
            raise ValueError("'active' em prior_unit do keyring deve ser booleano")

        prior_dropin = journal.get("prior_dropin")
        if not isinstance(prior_dropin, dict):
            raise ValueError("diario de keyring invalido: campo 'prior_dropin' ausente ou invalido")
        allowed_kpd_keys = {"exists", "is_project_owned", "content", "mode", "intent_to_remove", "removed_by_adoption"}
        if set(prior_dropin.keys()) != allowed_kpd_keys:
            diff = set(prior_dropin.keys()) ^ allowed_kpd_keys
            raise ValueError(f"chaves invalidas ou ausentes em prior_dropin: {sorted(diff)}")
        d_exists = prior_dropin.get("exists")
        if not isinstance(d_exists, bool):
            raise ValueError("'exists' em prior_dropin deve ser booleano")
        if not isinstance(prior_dropin.get("is_project_owned"), bool):
            raise ValueError("'is_project_owned' em prior_dropin deve ser booleano")
        if d_exists:
            if not isinstance(prior_dropin.get("content"), str):
                raise ValueError("content deve ser string quando exists=True em prior_dropin")
            if not isinstance(prior_dropin.get("mode"), int):
                raise ValueError("mode deve ser int quando exists=True em prior_dropin")
        else:
            if prior_dropin.get("content") is not None:
                raise ValueError("content deve ser None quando exists=False em prior_dropin")
            if prior_dropin.get("mode") is not None:
                raise ValueError("mode deve ser None quando exists=False em prior_dropin")
        if not isinstance(prior_dropin.get("intent_to_remove"), bool):
            raise ValueError("'intent_to_remove' em prior_dropin deve ser booleano")
        if not isinstance(prior_dropin.get("removed_by_adoption"), bool):
            raise ValueError("'removed_by_adoption' em prior_dropin deve ser booleano")

        if "error" in journal:
            _validate_typed_error(journal["error"], "error")
        if "rollback_error" in journal:
            _validate_typed_error(journal["rollback_error"], "rollback_error")


def _verify_journal_id_parity(
    containers: dict[str, dict[str, object]],
    journal: dict[str, object],
    target_path: Path | None = None,
    state_path: Path | None = None,
) -> None:
    """Verifica se os IDs atuais coincidem estritamente com os IDs gravados no diário."""
    _validate_journal_structure(journal, "workspace", target_path=target_path, state_path=state_path)
    journal_containers = journal.get("containers", {})
    if set(journal_containers.keys()) != set(containers.keys()):
        raise ValueError(
            f"Conjunto de containers divergente: registrado {sorted(journal_containers.keys())}, atual {sorted(containers.keys())}"
        )
    for role, j_info in journal_containers.items():
        jid = j_info.get("id")
        cid = containers[role].get("id")
        if jid != cid:
            raise ValueError(
                f"ID divergente para container '{role}': registrado {jid}, atual {cid}"
            )


def _verify_single_container_id(expected_id: str, name: str) -> None:
    """Verifica se o container atual no Podman possui exatamente o ID esperado."""
    if not expected_id:
        raise ValueError(f"ID esperado vazio para o container '{name}'")
    try:
        current_id = podman.out("inspect", name, "--format", "{{.Id}}").strip()
    except Exception as exc:
        raise RuntimeError(f"Falha ao inspecionar container '{name}': {exc}") from exc
    if current_id != expected_id:
        raise ValueError(f"ID divergente para container '{name}': esperado {expected_id}, atual {current_id}")


def _is_container_running(c_target: str) -> bool:
    """Verifica se um container está em execução por nome ou ID (falha fechado em erro)."""
    out = podman.out("inspect", c_target, "--format", "{{.State.Running}}").strip()
    return out.lower() == "true"


def _netns_producers(ws: str) -> list[str]:
    """Inventario read-only dos produtores conhecidos do namespace rootless.

    ESCOPO DECLARADO, nao promessa de exaustao. Qualquer processo que rode
    `podman unshare --rootless-netns` cria o namespace, e o conjunto de
    processos de um host nao e enumeravel daqui; afirmar completude seria
    afirmar o que nao se mediu. O que este inventario cobre sao as tres
    classes que importam para a coexistencia da adocao, e a versao anterior
    enxergava apenas a primeira metade da primeira:

    1. TODA entrada de `podman-restart.service.d/`, nossa ou alheia. O
       `ExecStartPre` de qualquer drop-in ali e um produtor, e um drop-in de
       terceiro nao deixa de produzir por nao ser nosso. Symlink e entrada
       nao-regular entram classificados, nunca silenciados: `is_file()` os
       apagava do inventario por seguir link ou por nao ser arquivo.
    2. As unidades que sobem containers, incluindo as LEGADAS: o proprio
       `podman-restart.service` quando habilitado — o mecanismo de boot do
       caminho legado — e as units `asb-*` presentes na raiz de configuracao
       que nao pertencem ao workspace desta transacao.
    3. Os containers, separando os rotulados com `asb.workspace=` dos NAO
       ROTULADOS. A contagem anterior derivava de `asb.workspace=` e portanto
       ignorava por construcao todo container sem esse label, que produz o
       namespace igual. `ps -a` e nao `ps`: um container parado com
       `should-start-on-boot` e produtor no proximo boot.

    Erro de consulta entra na lista como `unknown: ...`: nao saber e diferente
    de nao haver, e o operador que le o inventario precisa distinguir os dois.
    """
    producers: list[str] = []

    # 1. drop-ins do podman-restart.service (nossos e alheios)
    dropin = install.get_dropin_path()
    dropin_dir = dropin.parent
    try:
        entries = sorted(os.listdir(dropin_dir))
    except FileNotFoundError:
        entries = []
    except OSError as exc:
        producers.append(f"unknown: {dropin_dir} ilegivel ({exc})")
        entries = []
    for entry in entries:
        try:
            st = os.stat(dropin_dir / entry, follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError as exc:
            producers.append(f"unknown: {dropin_dir / entry} ilegivel ({exc})")
            continue
        if not stat.S_ISREG(st.st_mode):
            producers.append(f"dropin:{entry}(nao-regular)")
            continue
        if entry == dropin.name:
            try:
                _, ours, _, _ = install.read_project_dropin()
            except RuntimeError as exc:
                producers.append(f"unknown: {dropin} ilegivel ({exc})")
                continue
            producers.append(f"dropin:{entry}({'projeto' if ours else 'alheio'})")
        else:
            producers.append(f"dropin:{entry}(alheio)")

    # 2. unidades que sobem containers, legadas incluidas
    own = {f"asb-{ws}.target"} | {f"asb-{ws}-{role}.service" for role in CANONICAL_ROLES}
    # Uma raiz so, a do drop-in (`<config>/systemd/user`), que num host real E
    # `~/.config/systemd/user` — a raiz de units do manager. Acrescentar aqui a
    # raiz de `_resolve_paths()` parecia mais completo e nao era: sem
    # `ASB_SYSTEMD_UNIT_DIR` ela cai no HOME do operador, e o inventario de um
    # cenario isolado passava a listar as units reais dele, `asb-keyring.service`
    # inclusive. Diagnostico nao vale romper o isolamento que o brief exige.
    #
    # Uma raiz significa que um laco e um `seen_units` de deduplicacao nao tem o
    # que fazer: eram codigo inalcancavel, e sairam.
    unit_root = dropin_dir.parent
    # `systemctl --user enable podman-restart.service` se registra em disco como
    # link em `default.target.wants/`, e e por ele que a habilitacao e lida
    # aqui: consultar `is-enabled` alcancaria o manager do operador, que a
    # guarda de isolamento proibe e que tornaria o inventario dependente do
    # host. O link e a mesma fonte que o systemd le no boot. Limite declarado:
    # um `enable --runtime` manual nao aparece aqui, e `install.podman_restart()`
    # nunca usa `--runtime`.
    wants = unit_root / "default.target.wants" / "podman-restart.service"
    try:
        if wants.is_symlink() or wants.exists():
            producers.append("unit:podman-restart.service(habilitada em default.target.wants)")
    except OSError as exc:
        producers.append(f"unknown: {wants} ilegivel ({exc})")
    try:
        unit_entries = sorted(
            e for e in os.listdir(unit_root)
            if e.startswith("asb-") and e.endswith((".service", ".target"))
        )
    except FileNotFoundError:
        unit_entries = []
    except OSError as exc:
        producers.append(f"unknown: {unit_root} ilegivel ({exc})")
        unit_entries = []
    for entry in unit_entries:
        if entry not in own:
            producers.append(f"unit:{entry}(legada ou de outro workspace)")

    # 3. containers, rotulados e nao rotulados
    res_ps = podman.run("ps", "-a", "--format", "{{.Names}}|{{.Labels}}",
                        check=False, capture=True)
    if res_ps.returncode == 0:
        labelled_workspaces: set[str] = set()
        unlabelled = 0
        for line in res_ps.stdout.splitlines():
            if not line.strip():
                continue
            _, _, labels = line.partition("|")
            found = [item.split("=", 1)[1] for item in labels.split(",")
                     if item.startswith("asb.workspace=")]
            if found:
                labelled_workspaces.update(found)
            else:
                unlabelled += 1
        if labelled_workspaces:
            producers.append(f"workspaces_rotulados:{len(labelled_workspaces)}")
        if unlabelled:
            producers.append(f"containers_sem_label:{unlabelled}")
    else:
        producers.append(f"unknown: {res_ps.stderr.strip() or f'exit {res_ps.returncode}'}")

    return producers


def _collect_diagnostics(ws: str) -> dict[str, object]:
    """Coleta diagnósticos de coexistência: layout de credenciais, forwarder e netns."""
    cred_vol_candidates = [
        os.environ.get("ASB_CREDENTIALS_VOLUME"),
        f"asb-{ws}-credentials",
        f"{ws}-credentials",
    ]
    legacy_cred: bool | str = False
    for cred_vol in cred_vol_candidates:
        if cred_vol:
            res_ex = podman.run("volume", "exists", cred_vol, check=False, capture=True)
            if res_ex.returncode == 0:
                try:
                    mp = podman.out("volume", "inspect", cred_vol, "--format", "{{.Mountpoint}}").strip()
                    if mp and Path(mp).is_dir():
                        root_files = [f.name for f in Path(mp).iterdir() if f.is_file()]
                        if any(rf in root_files for rf in (".credentials.json", "credentials.json", "auth.json")):
                            legacy_cred = True
                    break
                except Exception as exc:
                    legacy_cred = f"unknown: {exc}"
                    break
            elif res_ex.returncode != 1:
                legacy_cred = f"unknown: {res_ex.stderr.strip() or f'exit {res_ex.returncode}'}"
                break

    fwd_needs_rec: bool | str = False
    fwd_candidates = [
        os.environ.get("ASB_FORWARDER_CONTAINER"),
        f"asb-{ws}-forwarder",
        f"{ws}-forwarder",
    ]
    for fwd_name in fwd_candidates:
        if fwd_name:
            res_ex = podman.run("container", "exists", fwd_name, check=False, capture=True)
            if res_ex.returncode == 0:
                try:
                    raw_inspect = podman.out("inspect", fwd_name)
                    if "net.ipv4.ip_unprivileged_port_start" not in raw_inspect:
                        fwd_needs_rec = True
                    break
                except Exception as exc:
                    fwd_needs_rec = f"unknown: {exc}"
                    break
            elif res_ex.returncode != 1:
                fwd_needs_rec = f"unknown: {res_ex.stderr.strip() or f'exit {res_ex.returncode}'}"
                break

    return {
        "legacy_credentials_layout": legacy_cred,
        "forwarder_needs_recreation": fwd_needs_rec,
        "rootless_netns_producers": _netns_producers(ws),
    }


# --- Ponto unico de mutacao --------------------------------------------------
#
# Adocao e rollback so mudam o host por estas funcoes. Cada uma revalida o ID
# de cada container da transacao IMEDIATAMENTE antes de agir: units, target e
# runtime.json operam pelo NOME do container, e um container recriado por
# fora com o mesmo nome entre duas acoes interrompe a proxima acao, nao a
# seguinte a ela. Qualquer `subprocess.run(["systemctl"...])` ou
# `podman.run(...)` mutante fora daqui e um defeito.


def _verify_ids(ids: list[tuple[str, str]]) -> None:
    for cid, cname in ids:
        _verify_single_container_id(cid, cname)


def _systemctl_mutate(ids: list[tuple[str, str]], *args: str) -> None:
    """Mutacao do manager: revalida IDs, executa e exige rc=0 (nenhum rc tolerado)."""
    _verify_ids(ids)
    res = _systemctl(*args)
    if res.returncode != 0:
        raise RuntimeError(
            f"systemctl --user {' '.join(args)} falhou (rc={res.returncode}): {res.stderr.strip() or res.stdout.strip()}"
        )


def _podman_mutate(ids: list[tuple[str, str]], *args: str) -> None:
    _verify_ids(ids)
    podman.run(*args, check=True)


def _write_file(ids: list[tuple[str, str]], path: Path, content: str, mode: int | None = None) -> None:
    _verify_ids(ids)
    _atomic_write_text(path, content, mode)


def _remove_file(path: Path) -> None:
    """Remove arquivo regular ou symlink; ausencia nao e erro."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _unlink_file(ids: list[tuple[str, str]], path: Path) -> None:
    if path.is_file() or path.is_symlink():
        _verify_ids(ids)
        _remove_file(path)


def _daemon_reload(ids: list[tuple[str, str]]) -> None:
    _systemctl_mutate(ids, "daemon-reload")


# Os `_ensure_*` consultam o estado, so emitem o comando que o estado exige e
# confirmam o resultado pelo parser estrito. Nenhuma tupla de "ausente" e
# aceita: um comando so e emitido quando deve funcionar, e entao rc != 0 e
# falha, sem excecao por mensagem ou codigo.


def _ensure_stopped(ids: list[tuple[str, str]], unit: str) -> None:
    for _ in range(3):
        _, active = _unit_state(unit)
        if active == "inactive":
            return
        _systemctl_mutate(ids, "reset-failed" if active == "failed" else "stop", unit)
    raise RuntimeError(f"{unit} nao ficou inativa apos stop/reset-failed")


def _ensure_disabled(ids: list[tuple[str, str]], unit: str) -> None:
    """Remove a habilitacao persistente E a de runtime (resume habilita sem --runtime)."""
    for _ in range(3):
        enabled, _ = _unit_state(unit)
        if enabled not in _ENABLED:
            return
        _systemctl_mutate(ids, "disable", *(("--runtime",) if enabled == "enabled-runtime" else ()), unit)
    raise RuntimeError(f"{unit} continua habilitada apos disable")


def _ensure_enabled(ids: list[tuple[str, str]], unit: str, scope: tuple[str, ...]) -> None:
    wanted = "enabled-runtime" if scope else "enabled"
    enabled, _ = _unit_state(unit)
    if enabled != wanted:
        _systemctl_mutate(ids, "enable", *scope, unit)
        enabled, _ = _unit_state(unit)
    if enabled != wanted:
        raise RuntimeError(f"{unit} ficou '{enabled}' apos enable (esperado '{wanted}')")


def _ensure_started(ids: list[tuple[str, str]], unit: str) -> None:
    """Restaura atividade de baseline: so emite start se a unit nao estiver ativa."""
    _, active = _unit_state(unit)
    if active != "active":
        _start_unit(ids, unit)


def _start_unit(ids: list[tuple[str, str]], unit: str) -> None:
    """start incondicional: num target ja ativo ele ainda puxa as Wants= inativas."""
    _systemctl_mutate(ids, "start", unit)
    _, active = _unit_state(unit)
    if active != "active":
        raise RuntimeError(f"{unit} ficou '{active}' apos start")


# --- Seam do manager systemd ------------------------------------------------


def _enable_scope(target_path: Path) -> tuple[str, ...]:
    """`--runtime` quando as units moram no diretorio volatil do manager.

    Uma unit em $XDG_RUNTIME_DIR/systemd/user some no logout; habilita-la de
    forma persistente deixaria em ~/.config um symlink para um arquivo que
    nao existira no proximo login.
    """
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "systemd" / "user"
    return ("--runtime",) if target_path.resolve() == runtime.resolve() else ()


def _require_manager_reads(target_path: Path) -> None:
    """Prova, antes de qualquer escrita, que o manager carrega units de target_path."""
    res = _systemctl("show", "--property=UnitPath", "--value")
    if res.returncode != 0 or res.stderr.strip():
        raise RuntimeError(f"falha ao consultar o search path do manager: {res.stderr.strip() or res.stdout.strip()}")
    if str(target_path) not in res.stdout.split():
        raise RuntimeError(
            f"diretorio de units {target_path} fora do search path do manager systemd --user; "
            "recusa antes de qualquer escrita"
        )


def _require_fragment(unit: str, expected: Path) -> None:
    """Prova que o manager resolveu `unit` para exatamente o arquivo gravado (sem sombra)."""
    res = _systemctl("show", "--property=FragmentPath", "--value", unit)
    if res.returncode != 0 or res.stderr.strip():
        raise RuntimeError(f"falha ao consultar FragmentPath de {unit}: {res.stderr.strip() or res.stdout.strip()}")
    got = res.stdout.strip()
    if got != str(expected):
        raise RuntimeError(f"manager resolveu {unit} para FragmentPath={got or '(nenhum)'}, esperado {expected}")


def _keyring_container_name() -> str:
    return os.environ.get("ASB_KEYRING_CONTAINER", "asb-keyring")


def _keyring_unit_name() -> str:
    """Unit do keyring nomeada pelo container, como asb-{ws}-{role}.service.

    Derivar do container (e nao de uma constante) impede que um ambiente com
    keyring isolado dependa da unit canonica `asb-keyring.service`.
    """
    return f"{_keyring_container_name()}.service"


# --- Diario, baseline e pos-condicoes ---------------------------------------


def _checkpoint(journal: dict[str, object], journal_file: Path, phase: str) -> str:
    journal["phase"] = phase
    _atomic_write_text(journal_file, json.dumps(journal, indent=2))
    return phase


def _record_failure(journal: dict[str, object], journal_file: Path, key: str, exc: BaseException) -> None:
    journal[key] = {
        "type": type(exc).__name__,
        "message": str(exc) or type(exc).__name__,
        "phase": str(journal.get("phase", "unknown")),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _atomic_write_text(journal_file, json.dumps(journal, indent=2))


def _require_file_baseline(path: Path, existed: bool, content: str | None, mode: int | None) -> None:
    if existed:
        if (
            path.is_symlink()
            or not path.is_file()
            or path.read_text(encoding="utf-8") != content
            or (path.stat().st_mode & 0o777) != mode
        ):
            raise RuntimeError(f"pos-condicao de rollback violada: {path} diverge do baseline (conteudo/modo)")
    elif path.exists() or path.is_symlink():
        raise RuntimeError(f"pos-condicao de rollback violada: {path} nao deveria existir")


def _require_unit_baseline(unit: str, enabled: bool, active: bool) -> None:
    is_enabled, is_active = _systemd_unit_status(unit)
    if (is_enabled, is_active) != (enabled, active):
        raise RuntimeError(
            f"pos-condicao de rollback violada: {unit} habilitada={is_enabled} ativa={is_active}, "
            f"baseline habilitada={enabled} ativa={active}"
        )


def _require_container_baseline(label: str, info: dict[str, object]) -> None:
    cid = str(info["id"])
    policy, retry = _inspect_container_restart_policy(cid)
    expected_policy = str(info["prior_restart_policy"])
    expected_retry = int(info["prior_retry_count"])
    if policy != expected_policy or (expected_policy == "on-failure" and retry != expected_retry):
        raise RuntimeError(
            f"pos-condicao de rollback violada para '{label}': restart_policy esperado '{expected_policy}' "
            f"(retry={expected_retry}), obteve '{policy}' (retry={retry})"
        )
    running = _is_container_running(cid)
    if running != (info["prior_state"] == "running"):
        raise RuntimeError(f"pos-condicao de rollback violada para '{label}': running={running} diverge do baseline")


def _restore_container(ids: list[tuple[str, str]], info: dict[str, object]) -> None:
    cid = str(info["id"])
    prior = (str(info["prior_restart_policy"]), int(info["prior_retry_count"]))
    current = _inspect_container_restart_policy(cid)
    if current[0] != prior[0] or (prior[0] == "on-failure" and current[1] != prior[1]):
        _podman_mutate(ids, "update", _format_restart_policy_arg(*prior), cid)
    running = _is_container_running(cid)
    if info["prior_state"] == "running" and not running:
        _podman_mutate(ids, "start", cid)
    elif info["prior_state"] != "running" and running:
        _podman_mutate(ids, "stop", "-t", "5", cid)


# Rank de cada fase do diario para a matriz de retomada.
_PHASE_RANK = {
    "inventory": 0,
    "units_prepared": 1,
    "policies_updated": 2,
    "supervision_configured": 3,
    "supervision_started": 3,
    "readiness_verified": 4,
}


def _phase_refusal(phase: str, detail: str) -> ValueError:
    return ValueError(f"diario na fase '{phase}' incoerente com o host: {detail}; recusa antes de qualquer mutacao")


def _require_fragment_for_phase(phase: str, unit: str, expected: Path) -> None:
    try:
        _require_fragment(unit, expected)
    except RuntimeError as exc:
        raise _phase_refusal(phase, str(exc)) from exc


def _require_file_for_phase(phase: str, path: Path, content: str) -> None:
    if path.is_symlink() or not path.is_file() or path.read_text(encoding="utf-8") != content:
        raise _phase_refusal(phase, f"{path} ausente ou diferente do conteudo que a fase garante")


# --- Workspace ---------------------------------------------------------------


def _workspace_artifacts(
    ws: str,
    containers: dict[str, dict[str, object]],
    target_path: Path,
    manifest_file: Path,
    launcher_file: Path,
    revision: str,
    keyring_container: str,
) -> dict[Path, str]:
    """Conteudo exato de cada arquivo que a adocao grava, na ordem de escrita.

    A adocao grava exatamente isto e a matriz de fases compara o disco contra
    isto: uma unica fonte impede que as duas divirjam.
    """
    target_name = f"asb-{ws}.target"
    ssh_port = None
    for p_info in list(containers.get("proxy", {}).get("ports", [])) + list(containers.get("agent", {}).get("ports", [])):
        cp = str(p_info.get("container_port", ""))
        if cp in ("22", "22/tcp", "2222", "2222/tcp"):
            hp = p_info.get("host_port")
            if hp:
                # Presente e impresentavel NAO e ausente: deixar `ssh_port` em
                # None gravaria no runtime.json um workspace indistinguivel de
                # outro que nunca teve mapeamento SSH (R6).
                try:
                    ssh_port = int(hp)
                except (ValueError, TypeError) as exc:
                    raise RuntimeError(
                        f"porta SSH do workspace '{ws}' presente mas ilegivel "
                        f"(host_port={hp!r}); recusa antes de qualquer mutacao"
                    ) from exc
                break

    all_mounts: list[object] = []
    for c in containers.values():
        for m in c.get("mounts", []):
            if m not in all_mounts:
                all_mounts.append(m)

    manifest_data = {
        "schemaVersion": 1,
        "workspace": ws,
        "revision": revision,
        "runtime_type": "systemd",
        "runtime_backend": "systemd",
        "ssh_port": ssh_port,
        "mounts": all_mounts,
        "containers": {
            role: {
                "name": c["name"],
                "id": c["id"],
                "unit": c["unit_name"],
                "prior_restart_policy": c.get("prior_restart_policy"),
                "prior_retry_count": c.get("prior_retry_count", 0),
                "prior_state": c.get("prior_state"),
            }
            for role, c in containers.items()
        },
    }
    # Contexto de isolamento que a sonda de prontidao le do manifesto: o
    # ExecStartPost roda sob o systemd, sem o ambiente de quem adotou. Sem
    # estas chaves, `runtime_check` cairia no keyring default (o do operador).
    # Mesmo conjunto que `lifecycle.up` grava no runtime.json.
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
    manifest_data["keyring_container"] = keyring_container

    files: dict[Path, str] = {manifest_file: json.dumps(manifest_data, indent=2)}
    proxy_running = containers.get("proxy", {}).get("prior_state") == "running"
    for role, c in containers.items():
        unit = ContainerUnit(
            name=str(c["name"]),
            container_id=str(c["id"]),
            role=role,
            unit_name=str(c["unit_name"]),
            target_name=target_name,
            helper_path=launcher_file,
            manifest_path=manifest_file,
            wants_proxy=proxy_running,
            keyring_unit=f"{keyring_container}.service",
        )
        files[target_path / str(c["unit_name"])] = render_unit(unit)
    # O `Wants=` lista TODOS os containers do workspace. Escopa-lo ao subconjunto
    # que estava rodando quebra o `resume`: `lifecycle.resume` sobe o workspace
    # apenas habilitando e iniciando este target, entao um workspace adotado
    # inteiramente parado ficaria com `Wants=` vazio e nao subiria nada. O
    # problema que o escopo tentava resolver — o boot ressuscitando um container
    # parado — e tratado onde pertence, em `_require_workspace_phase`, que
    # distingue "rodando sob unit ativa" de "rodando fora da supervisao".
    files[target_path / target_name] = render_target(
        target_name, units=[str(c["unit_name"]) for c in containers.values()]
    )
    return files


def _probe_workspace_readiness(
    containers: dict[str, dict[str, object]], check_file: Path, manifest_file: Path
) -> None:
    """Sonda de prontidao de cada papel que estava rodando; levanta RuntimeError."""
    for role, timeout in (("proxy", 95.0), ("agent", 60.0)):
        if role in containers and containers[role].get("prior_state") == "running":
            res = subprocess.run(
                [sys.executable, str(check_file), "--role", role, "--manifest", str(manifest_file)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if res.returncode != 0:
                raise RuntimeError(
                    f"sonda de prontidao do {role} falhou (code {res.returncode}): {res.stderr.strip() or res.stdout.strip()}"
                )


def _probe_keyring_readiness(c_name: str) -> None:
    """Sonda bounded e tipada do Secret Service; levanta RuntimeError."""
    from .readiness import probe_keyring, wait_until
    probe_res = wait_until(
        lambda to: probe_keyring(container=c_name, timeout=to),
        timeout=10.0,
    )
    if probe_res.state != "healthy":
        raise RuntimeError(
            f"sonda de prontidao do Secret Service ({c_name}) falhou: "
            f"{probe_res.code} -> {probe_res.remediation}"
        )


def _require_readiness_for_phase(phase: str, probe) -> None:
    """`readiness_verified` promete prontidao: repete a sonda antes de confiar nela."""
    if phase != "readiness_verified":
        return
    try:
        probe()
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        raise _phase_refusal(phase, f"prontidao nao confirmada: {exc}") from exc


def _resolve_keyring_container(manifest_baseline: dict[str, object]) -> str:
    """Keyring ao qual ESTE workspace esta ligado, sem inventar valor.

    Ordem: `ASB_KEYRING_CONTAINER` do ambiente; senao o `keyring_container` ja
    gravado no runtime.json do workspace; so entao o default. Resolver sempre
    pelo ambiente colapsaria "variavel ausente" em "operador usa asb-keyring" e
    sobrescreveria, numa adocao feita de outro shell, o keyring real de um
    workspace criado com `ASB_KEYRING_CONTAINER` proprio — a sonda e o
    `After=`/`Wants=` passariam a apontar para outro container.
    """
    from_env = os.environ.get("ASB_KEYRING_CONTAINER")
    if from_env:
        return from_env
    content = manifest_baseline.get("content")
    if content is None:
        # Workspace legado, sem runtime.json: ausencia legitima, cai no default.
        return _keyring_container_name()
    if not isinstance(content, str):
        raise RuntimeError(f"runtime.json do baseline com tipo invalido: {type(content).__name__}")
    try:
        prior = json.loads(content)
    except ValueError as exc:
        # Presente e ilegivel NAO e ausente: cair no default aqui sobrescreveria
        # o unico registro do keyring real do workspace.
        raise RuntimeError(
            f"runtime.json do workspace presente mas ilegivel ({exc}); "
            "recusa antes de qualquer mutacao"
        ) from exc
    if not isinstance(prior, dict):
        raise RuntimeError(
            "runtime.json do workspace presente mas nao e um objeto JSON; "
            "recusa antes de qualquer mutacao"
        )
    recorded = prior.get("keyring_container")
    if isinstance(recorded, str) and recorded:
        return recorded
    # Manifesto legivel que nunca registrou keyring (ex.: `up` sem a variavel):
    # ausencia de fato, nao ilegibilidade.
    return _keyring_container_name()


def _require_workspace_phase(
    phase: str,
    ws: str,
    containers: dict[str, dict[str, object]],
    files: dict[Path, str],
    target_path: Path,
    scope: tuple[str, ...],
) -> None:
    """Matriz fase -> artefatos/pos-condicoes para retomar um diario de workspace.

    Paths derivados e prior_state coerentes nao bastam: um diario plausivel em
    `readiness_verified` sem units, politicas ou supervisao faria a adocao
    pular todas as etapas e reportar sucesso. Cada fase so e aceita se o que
    ela promete estiver no host. Somente leitura; roda antes de qualquer
    mutacao, inclusive antes de regravar o diario.

      units_prepared     runtime.json, units e target com o conteudo exato, e
                         o manager resolvendo cada unit para esse arquivo
      policies_updated   + restart policy 'no' em todo container
      supervision_conf.  + nenhum container que a adocao deixou parado rodando
                         fora da supervisao (rodando sob a propria unit ativa
                         e valido: e o systemd, no boot ou num resume)
      supervision_*      + o acima, mais target habilitado e a unit de cada
                         container que estava rodando ativa, com ele rodando
    """
    rank = _PHASE_RANK[phase]
    if rank == 0:
        return
    for path, content in files.items():
        _require_file_for_phase(phase, path, content)
    target_name = f"asb-{ws}.target"
    for unit in (target_name, *(str(c["unit_name"]) for c in containers.values())):
        _require_fragment_for_phase(phase, unit, target_path / unit)
    if rank < 2:
        return
    for c in containers.values():
        policy, _ = _inspect_container_restart_policy(str(c["id"]))
        if policy != "no":
            raise _phase_refusal(phase, f"restart policy de {c['name']} e '{policy}', esperado 'no'")
    if rank < 3:
        return
    # Container que a adocao deixou parado, mas que esta rodando FORA da
    # supervisao, e o estado que estas fases prometem nao existir — e foi o
    # achado do gate: "iniciado externamente ... rodando sem supervisao ativa".
    #
    # Rodar sob a propria unit ativa e outra coisa: e a supervisao funcionando.
    # O target tem `WantedBy=default.target` e lista todo o workspace em
    # `Wants=`, entao o systemd o sobe no boot seguinte; recusar ai acusaria de
    # bypass externo o proprio manager, e um `resume` legitimo tambem cairia na
    # recusa. A distincao e a unit, nao o container.
    for c in containers.values():
        if c.get("prior_state") == "running" or not _is_container_running(str(c["id"])):
            continue
        _, active = _unit_state(str(c["unit_name"]))
        # `activating` e a janela normal do boot: a unit e Type=exec com
        # ExecStartPost rodando a sonda de prontidao (ate 95s no proxy, 60s no
        # agente), entao o container ja roda enquanto a unit segue ativando.
        # `deactivating`/`reloading` sao igualmente o manager agindo. Recusar
        # ai acusaria o systemd de bypass — o mesmo falso positivo que esta
        # checagem existe para evitar, so que deslocado no tempo.
        if active == "active" or active in _TRANSITIONAL:
            continue
        raise _phase_refusal(
            phase,
            f"{c['name']} esta em execucao com {c['unit_name']} em '{active}': "
            "rodando fora da supervisao")
    if phase not in ("supervision_started", "readiness_verified"):
        return
    wanted = "enabled-runtime" if scope else "enabled"
    enabled, _ = _unit_state(target_name)
    if enabled != wanted:
        raise _phase_refusal(phase, f"{target_name} esta '{enabled}', esperado '{wanted}'")
    for c in containers.values():
        if c.get("prior_state") == "running":
            _, active = _unit_state(str(c["unit_name"]))
            if active != "active" or not _is_container_running(str(c["id"])):
                raise _phase_refusal(phase, f"{c['unit_name']} deveria estar ativa com {c['name']} em execucao")


def _rollback_workspace_from_journal(
    ws: str,
    journal: dict[str, object],
    state_path: Path,
    target_path: Path,
) -> None:
    """Restaura units, manifesto e politicas a partir do diario sem recriar containers."""
    containers = journal["containers"]
    prior_units = journal["prior_units"]
    services = prior_units["services"]
    manifest_baseline = journal["runtime_manifest_baseline"]
    ids = [(str(c["id"]), str(c["name"])) for c in containers.values()]
    target_name = f"asb-{ws}.target"
    scope = _enable_scope(target_path)
    _require_manager_reads(target_path)

    # 1. Desfazer a supervisao das units do diario, e so delas.
    for unit in (target_name, *services):
        _ensure_stopped(ids, unit)
        _ensure_disabled(ids, unit)

    # 2. Arquivos de volta ao baseline.
    files = [(target_path / target_name, prior_units["target_existed"],
              prior_units["target_content"], prior_units["target_mode"])]
    files += [(target_path / u, s["existed"], s["content"], s["mode"]) for u, s in services.items()]
    files.append((state_path / "runtime.json", manifest_baseline["existed"],
                  manifest_baseline["content"], manifest_baseline["mode"]))
    for path, existed, content, mode in files:
        if existed:
            _write_file(ids, path, content, mode)
        else:
            _unlink_file(ids, path)
    _daemon_reload(ids)

    # 3. Habilitacao e atividade de baseline.
    states = [(target_name, prior_units["target_enabled"], prior_units["target_active"])]
    states += [(u, s["enabled"], s["active"]) for u, s in services.items()]
    for unit, enabled, active in states:
        if enabled:
            _ensure_enabled(ids, unit, scope)
        if active:
            _ensure_started(ids, unit)

    # 4. Politica e estado dos containers.
    for c in containers.values():
        _restore_container(ids, c)

    # 5. Pos-condicoes, somente leitura.
    for role, c in containers.items():
        _require_container_baseline(role, c)
    for path, existed, content, mode in files:
        _require_file_baseline(path, existed, content, mode)
    for unit, enabled, active in states:
        _require_unit_baseline(unit, enabled, active)


def adopt_workspace(
    ws: str,
    *,
    apply: bool = False,
    target_dir: Path | None = None,
    state_dir: Path | None = None,
    helper_path: Path | None = None,
    runtime_manifest: dict[str, object] | None = None,
) -> dict[str, object]:
    """Adota supervisão systemd Type=exec sem recriar containers (schema 1).

    A prontidão é sempre exigida, como em `adopt_keyring` e como no `up
    --runtime systemd` (que já renderiza o `ExecStartPost` por default de
    `ContainerUnit`): `readiness_verified` só é gravado depois da sonda.
    """
    _validate_safe_name(ws, "workspace")
    state_path, target_path = _resolve_paths(ws, target_dir, state_dir)
    target_name = f"asb-{ws}.target"
    target_file = target_path / target_name
    manifest_file = state_path / "runtime.json"
    journal_file = state_path / "journal.json"

    with _AdoptionLock(state_path, ws, create=apply):
        containers = _inspect_workspace_containers(ws)
        # Contrato de estado misto: agente rodando com proxy parado e invalido (falha fechado)
        if containers.get("agent", {}).get("prior_state") == "running" and containers.get("proxy", {}).get("prior_state") != "running":
            raise ValueError(f"workspace '{ws}' em estado inconsistente: agente em execucao com proxy parado")

        target_existed = target_file.is_file()
        target_content = target_file.read_text(encoding="utf-8") if target_existed else None
        target_mode = (target_file.stat().st_mode & 0o777) if target_existed else None
        target_enabled, target_active = _systemd_unit_status(target_name)

        services: dict[str, dict[str, object]] = {}
        for c_info in containers.values():
            u_name = str(c_info["unit_name"])
            u_file = target_path / u_name
            u_existed = u_file.is_file()
            u_enabled, u_active = _systemd_unit_status(u_name)
            services[u_name] = {
                "file": str(u_file),
                "existed": u_existed,
                "content": u_file.read_text(encoding="utf-8") if u_existed else None,
                "mode": (u_file.stat().st_mode & 0o777) if u_existed else None,
                "enabled": u_enabled,
                "active": u_active,
            }

        manifest_existed = manifest_file.is_file()
        manifest_baseline = {
            "file": str(manifest_file),
            "existed": manifest_existed,
            "content": manifest_file.read_text(encoding="utf-8") if manifest_existed else None,
            "mode": (manifest_file.stat().st_mode & 0o777) if manifest_existed else None,
        }

        diag = _collect_diagnostics(ws)

        existing_journal = None
        if journal_file.is_file():
            try:
                existing_journal = json.loads(journal_file.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ValueError(f"diario corrompido em {journal_file}: {exc}") from exc
            _validate_journal_structure(existing_journal, "workspace", ws, target_path=target_path, state_path=state_path)
            _verify_journal_id_parity(containers, existing_journal, target_path=target_path, state_path=state_path)

        if isinstance(existing_journal, dict) and existing_journal["phase"] != "rolled_back":
            prior_units = existing_journal["prior_units"]
            manifest_baseline = existing_journal["runtime_manifest_baseline"]
            for role, c_info in containers.items():
                orig_c = existing_journal["containers"][role]
                c_info["prior_restart_policy"] = orig_c["prior_restart_policy"]
                c_info["prior_retry_count"] = orig_c["prior_retry_count"]
                c_info["prior_state"] = orig_c["prior_state"]
            resumed_phase = str(existing_journal["phase"])
        else:
            prior_units = {
                "target_file": str(target_file),
                "target_existed": target_existed,
                "target_content": target_content,
                "target_mode": target_mode,
                "target_enabled": target_enabled,
                "target_active": target_active,
                "services": services,
            }
            resumed_phase = "inventory"

        inventory: dict[str, object] = {
            "schemaVersion": 1,
            "workspace": ws,
            "containers": containers,
            "prior_units": prior_units,
            "runtime_manifest_baseline": manifest_baseline,
            "diagnostics": diag,
            "phase": resumed_phase,
        }

        if not apply:
            return {
                "status": "dry_run",
                "workspace": ws,
                "inventory": inventory,
            }

        ids = [(str(c["id"]), str(c["name"])) for c in containers.values()]
        scope = _enable_scope(target_path)
        _require_manager_reads(target_path)
        launcher_file, check_file, rev = _resolve_versioned_runtime(helper_path, runtime_manifest)
        keyring_container = _resolve_keyring_container(manifest_baseline)
        files = _workspace_artifacts(ws, containers, target_path, manifest_file, launcher_file, rev,
                                     keyring_container)
        units = [target_name, *(str(c["unit_name"]) for c in containers.values())]
        _require_workspace_phase(resumed_phase, ws, containers, files, target_path, scope)
        _require_readiness_for_phase(
            resumed_phase, lambda: _probe_workspace_readiness(containers, check_file, manifest_file)
        )

        journal = dict(inventory)
        _atomic_write_text(journal_file, json.dumps(journal, indent=2))

        try:
            phase = resumed_phase

            if phase == "inventory":
                for path, content in files.items():
                    _write_file(ids, path, content)
                _verify_unit_files([target_path / u for u in units], target_dir=target_path)
                _daemon_reload(ids)
                for unit in units:
                    _require_fragment(unit, target_path / unit)
                phase = _checkpoint(journal, journal_file, "units_prepared")

            if phase == "units_prepared":
                for c in containers.values():
                    _podman_mutate(ids, "update", "--restart=no", str(c["id"]))
                    cur_pol, _ = _inspect_container_restart_policy(str(c["id"]))
                    if cur_pol != "no":
                        raise RuntimeError(f"falha ao aplicar restart=no no container {c['name']}: politica e {cur_pol}")
                phase = _checkpoint(journal, journal_file, "policies_updated")

            if phase == "policies_updated":
                running = [c for c in containers.values() if c.get("prior_state") == "running"]
                if not running:
                    phase = _checkpoint(journal, journal_file, "supervision_configured")
                    return {
                        "status": "applied",
                        "workspace": ws,
                        "phase": phase,
                        "inventory": inventory,
                    }

                _ensure_enabled(ids, target_name, scope)
                if len(running) == len(containers):
                    _start_unit(ids, target_name)
                else:
                    for c in running:
                        _start_unit(ids, str(c["unit_name"]))

                for role, c in containers.items():
                    target_id = str(c["id"])
                    is_run = _is_container_running(target_id)
                    if c.get("prior_state") == "running" and _unit_state(str(c["unit_name"]))[1] != "active" and is_run:
                        raise RuntimeError(f"unidade {c['unit_name']} nao ficou ativa: container {role} sem supervisao")
                    if c.get("prior_state") == "running" and not is_run:
                        res_show = _systemctl("show", str(c["unit_name"]), "--property=ExecStartPost")
                        status_match = re.search(r"\bstatus=(\d+)\b", res_show.stdout)
                        if status_match and int(status_match.group(1)) != 0:
                            raise RuntimeError(f"sonda de prontidao do {role} falhou no ExecStartPost (status {status_match.group(1)})")
                        raise RuntimeError(f"container {role} ({target_id}) deveria estar em execucao apos adocao, mas esta parado")
                    elif c.get("prior_state") != "running" and is_run:
                        raise RuntimeError(f"container {role} ({target_id}) deveria permanecer parado apos adocao, mas foi iniciado")

                phase = _checkpoint(journal, journal_file, "supervision_started")

            if phase == "supervision_started":
                _probe_workspace_readiness(containers, check_file, manifest_file)

                phase = _checkpoint(journal, journal_file, "readiness_verified")

            return {
                "status": "applied",
                "workspace": ws,
                "phase": phase,
                "inventory": inventory,
            }

        except Exception as exc:
            _record_failure(journal, journal_file, "error", exc)
            try:
                _rollback_workspace_from_journal(ws, journal, state_path, target_path)
                _checkpoint(journal, journal_file, "rolled_back")
            except Exception as rb_exc:
                _record_failure(journal, journal_file, "rollback_error", rb_exc)
            raise


def rollback_workspace(
    ws: str,
    *,
    target_dir: Path | None = None,
    state_dir: Path | None = None,
) -> dict[str, object]:
    """Reverte supervisão systemd de um workspace para legacy sem recriar containers."""
    _validate_safe_name(ws, "workspace")
    state_path, target_path = _resolve_paths(ws, target_dir, state_dir)
    journal_file = state_path / "journal.json"

    with _AdoptionLock(state_path, ws, create=False):
        if not journal_file.is_file():
            raise FileNotFoundError(f"diario ausente em {journal_file}: impossivel determinar estado anterior para rollback")

        try:
            journal = json.loads(journal_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"diario corrompido em {journal_file}: {exc}") from exc

        _validate_journal_structure(journal, "workspace", ws, target_path=target_path, state_path=state_path)
        fresh_containers = _inspect_workspace_containers(ws)
        _verify_journal_id_parity(fresh_containers, journal, target_path=target_path, state_path=state_path)

        try:
            _rollback_workspace_from_journal(ws, journal, state_path, target_path)
        except Exception as exc:
            _record_failure(journal, journal_file, "error", exc)
            raise

        _checkpoint(journal, journal_file, "rolled_back")
        return {"status": "rolled_back", "workspace": ws}


# --- Keyring -----------------------------------------------------------------


def _inspect_keyring_container_info(container_name: str) -> dict[str, object]:
    """Inspeciona estritamente o container do keyring."""
    if not container_name or any(c in container_name for c in ("/", "\\", "..", " ", "\t", "\n", "\r")):
        raise ValueError(f"nome de container de keyring invalido ou inseguro: {container_name!r}")
    if not podman.exists("container", container_name):
        raise ValueError(f"container de keyring '{container_name}' nao encontrado")

    raw = podman.out("container", "inspect", container_name, "--format", "{{json .}}")
    data = json.loads(raw)
    cid = str(data.get("Id", "")).strip()
    if not cid or any(c in cid for c in ("/", "\\", "..", " ", "\t", "\n", "\r")):
        raise ValueError(f"ID de container invalido ou vazio para keyring '{container_name}': {cid!r}")

    cfg = data.get("Config", {})
    state = data.get("State", {})
    status = "running" if state.get("Running") else (state.get("Status") or "stopped")
    host_cfg = data.get("HostConfig", {})
    restart_obj = host_cfg.get("RestartPolicy", {}) or {}
    policy = restart_obj.get("Name") or "unless-stopped"
    retry_count = int(restart_obj.get("MaximumRetryCount") or 0)
    image = cfg.get("Image", "")

    return {
        "id": cid,
        "name": container_name,
        "prior_state": status,
        "prior_restart_policy": policy,
        "prior_retry_count": retry_count,
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


def _require_keyring_phase(
    phase: str,
    unit_name: str,
    unit_file: Path,
    rendered: str,
    cid: str,
    scope: tuple[str, ...],
    prior_dropin: dict[str, object],
) -> None:
    """Matriz fase -> artefatos/pos-condicoes para retomar o diario do keyring.

    Mesmo contrato do workspace: unit com o conteudo exato e resolvida pelo
    manager (units_prepared), politica 'no' (policies_updated), unit
    habilitada e ativa com o container rodando (supervision_*), e o drop-in
    do projeto removido pela adocao (readiness_verified).
    """
    rank = _PHASE_RANK[phase]
    if rank == 0:
        return
    _require_file_for_phase(phase, unit_file, rendered)
    _require_fragment_for_phase(phase, unit_name, unit_file)
    if rank < 2:
        return
    policy, _ = _inspect_container_restart_policy(cid)
    if policy != "no":
        raise _phase_refusal(phase, f"restart policy do keyring e '{policy}', esperado 'no'")
    if phase not in ("supervision_started", "readiness_verified"):
        return
    wanted = "enabled-runtime" if scope else "enabled"
    enabled, active = _unit_state(unit_name)
    if enabled != wanted or active != "active" or not _is_container_running(cid):
        raise _phase_refusal(phase, f"{unit_name} deveria estar '{wanted}' e ativa com o container em execucao")
    if phase == "readiness_verified" and prior_dropin["exists"] and prior_dropin["is_project_owned"]:
        dropin = get_dropin_path()
        if not prior_dropin["removed_by_adoption"] or dropin.is_file() or dropin.is_symlink():
            raise _phase_refusal(phase, "drop-in do projeto deveria ter sido removido pela adocao")


def _rollback_keyring_from_journal(
    journal: dict[str, object],
    target_path: Path,
) -> None:
    """Restaura unit, drop-in e politica do keyring sem recriar o container.

    O drop-in so e restaurado se a adocao o removeu, ou pode te-lo removido
    (intencao registrada e arquivo ausente). Um drop-in presente que a adocao
    nao removeu nao pertence a ela e fica intocado.
    """
    container = journal["container"]
    prior_unit = journal["prior_unit"]
    prior_dropin = journal["prior_dropin"]
    ids = [(str(container["id"]), str(container["name"]))]
    unit_name = _keyring_unit_name()
    unit_file = target_path / unit_name
    scope = _enable_scope(target_path)
    _require_manager_reads(target_path)

    _ensure_stopped(ids, unit_name)
    _ensure_disabled(ids, unit_name)

    if prior_unit["existed"]:
        _write_file(ids, unit_file, prior_unit["content"], prior_unit["mode"])
    else:
        _unlink_file(ids, unit_file)

    dropin = get_dropin_path()
    restore_dropin = bool(prior_dropin["removed_by_adoption"]) or (
        bool(prior_dropin["intent_to_remove"]) and not (dropin.is_file() or dropin.is_symlink())
    )
    if restore_dropin:
        # Uma validacao aqui autorizaria a ENTRADA e mais nada: mkdir, escrita,
        # chmod e daemon-reload acontecem todos depois dela. O gancho revalida
        # imediatamente antes de cada um, como na remocao.
        restore_project_dropin(
            content=prior_dropin["content"],
            mode=prior_dropin["mode"],
            verify=lambda: _verify_ids(ids),
        )

    _daemon_reload(ids)
    if prior_unit["enabled"]:
        _ensure_enabled(ids, unit_name, scope)
    if prior_unit["active"]:
        _ensure_started(ids, unit_name)

    _restore_container(ids, container)

    _require_container_baseline("keyring", container)
    _require_file_baseline(unit_file, prior_unit["existed"], prior_unit["content"], prior_unit["mode"])
    _require_unit_baseline(unit_name, prior_unit["enabled"], prior_unit["active"])
    if restore_dropin:
        _require_file_baseline(dropin, True, prior_dropin["content"], prior_dropin["mode"])


def adopt_keyring(
    *,
    apply: bool = False,
    target_dir: Path | None = None,
    state_dir: Path | None = None,
    helper_path: Path | None = None,
    runtime_manifest: dict[str, object] | None = None,
) -> dict[str, object]:
    """Adota o keyring singleton sob supervisão systemd sem recriar containers."""
    state_path, target_path = _resolve_paths("", target_dir, state_dir)
    c_name = _keyring_container_name()
    unit_name = _keyring_unit_name()
    _validate_safe_name(unit_name, "unit_name")
    unit_file = target_path / unit_name
    journal_file = state_path / "keyring-journal.json"

    with _AdoptionLock(state_path, "keyring", create=apply):
        info = _inspect_keyring_container_info(c_name)

        unit_existed = unit_file.is_file()
        unit_content = unit_file.read_text(encoding="utf-8") if unit_existed else None
        unit_mode = (unit_file.stat().st_mode & 0o777) if unit_existed else None
        unit_enabled, unit_active = _systemd_unit_status(unit_name)

        # Leitura unica: conteudo e modo saem do mesmo descritor `O_NOFOLLOW`
        # que decidiu a existencia. Em tres chamadas separadas, `read_text()` e
        # `stat()` seguiriam um symlink plantado no meio, e o baseline gravado
        # no diario seria de arquivo alheio — que o rollback restauraria como
        # se fosse nosso.
        dropin_exists, dropin_ours, dropin_content, dropin_mode = install.read_project_dropin()

        existing_journal = None
        if journal_file.is_file():
            try:
                existing_journal = json.loads(journal_file.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ValueError(f"diario de keyring corrompido em {journal_file}: {exc}") from exc
            _validate_journal_structure(existing_journal, "keyring", expected_unit_name=unit_name, target_path=target_path, state_path=state_path)
            jid = existing_journal["container"]["id"]
            if jid != info["id"]:
                raise ValueError(f"ID divergente para keyring: registrado {jid}, atual {info['id']}")

        if isinstance(existing_journal, dict) and existing_journal["phase"] != "rolled_back":
            prior_unit = existing_journal["prior_unit"]
            prior_dropin = existing_journal["prior_dropin"]
            orig_c = existing_journal["container"]
            info["prior_restart_policy"] = orig_c["prior_restart_policy"]
            info["prior_retry_count"] = orig_c["prior_retry_count"]
            info["prior_state"] = orig_c["prior_state"]
            resumed_phase = str(existing_journal["phase"])
        else:
            prior_unit = {
                "file": str(unit_file),
                "existed": unit_existed,
                "content": unit_content,
                "mode": unit_mode,
                "enabled": unit_enabled,
                "active": unit_active,
            }
            prior_dropin = {
                "exists": dropin_exists,
                "is_project_owned": dropin_ours,
                "content": dropin_content,
                "mode": dropin_mode,
                "intent_to_remove": False,
                "removed_by_adoption": False,
            }
            resumed_phase = "inventory"

        inventory = {
            "schemaVersion": 1,
            "component": "keyring",
            "container": info,
            "prior_unit": prior_unit,
            "prior_dropin": prior_dropin,
            "phase": resumed_phase,
        }

        if not apply:
            return {
                "status": "dry_run",
                "component": "keyring",
                "inventory": inventory,
            }

        ids = [(str(info["id"]), c_name)]
        scope = _enable_scope(target_path)
        _require_manager_reads(target_path)
        launcher_file, _, _ = _resolve_versioned_runtime(helper_path, runtime_manifest)
        rendered = _render_keyring_unit(c_name, launcher_file)
        _require_keyring_phase(resumed_phase, unit_name, unit_file, rendered, str(info["id"]), scope, prior_dropin)
        _require_readiness_for_phase(resumed_phase, lambda: _probe_keyring_readiness(c_name))

        journal = dict(inventory)
        _atomic_write_text(journal_file, json.dumps(journal, indent=2))

        try:
            phase = resumed_phase

            if phase == "inventory":
                _write_file(ids, unit_file, rendered)
                _verify_unit_files([unit_file], target_dir=target_path)
                _daemon_reload(ids)
                _require_fragment(unit_name, unit_file)
                phase = _checkpoint(journal, journal_file, "units_prepared")

            if phase == "units_prepared":
                _podman_mutate(ids, "update", "--restart=no", str(info["id"]))
                cur_pol, _ = _inspect_container_restart_policy(str(info["id"]))
                if cur_pol != "no":
                    raise RuntimeError(f"falha ao aplicar restart=no no keyring: politica e {cur_pol}")
                phase = _checkpoint(journal, journal_file, "policies_updated")

            if phase == "policies_updated":
                if info.get("prior_state") != "running":
                    phase = _checkpoint(journal, journal_file, "supervision_configured")
                    return {
                        "status": "applied",
                        "component": "keyring",
                        "phase": phase,
                        "inventory": inventory,
                    }
                _ensure_enabled(ids, unit_name, scope)
                _start_unit(ids, unit_name)
                phase = _checkpoint(journal, journal_file, "supervision_started")

            if phase == "supervision_started":
                _probe_keyring_readiness(c_name)

                pd = journal["prior_dropin"]
                if pd["exists"] and pd["is_project_owned"] and not pd["removed_by_adoption"]:
                    pd["intent_to_remove"] = True
                    # Simetria com a escrita de `removed_by_adoption` adiante: a
                    # doutrina de ponto unico de mutacao deste arquivo nao abre
                    # excecao para escrita de diario. Nao era explorravel (o
                    # campo nao carrega o ID e a proxima linha revalidava), mas a
                    # assimetria era um convite a erro de leitura.
                    _verify_ids(ids)
                    _atomic_write_text(journal_file, json.dumps(journal, indent=2))
                    _verify_ids(ids)
                    # `verify` revalida a identidade dentro da remocao, imediatamente
                    # antes do unlink e do daemon-reload: sem ele, o `_verify_ids`
                    # acima autoriza a entrada e as duas mutacoes seguintes rodam
                    # sob um container que pode ter sido recriado no meio.
                    if not remove_project_dropin(
                        expected_content=pd["content"],
                        expected_mode=pd["mode"],
                        verify=lambda: _verify_ids(ids),
                    ):
                        raise RuntimeError("falha ao remover drop-in do projeto: arquivo nao encontrado ou alheio")
                    # A conclusao tambem e guardada: gravar `removed_by_adoption` e
                    # cravar `readiness_verified` para um ID que ja nao existe seria
                    # registrar sucesso sobre outro container.
                    _verify_ids(ids)
                    pd["removed_by_adoption"] = True
                    _atomic_write_text(journal_file, json.dumps(journal, indent=2))

                phase = _checkpoint(journal, journal_file, "readiness_verified")

            return {
                "status": "applied",
                "component": "keyring",
                "phase": phase,
                "inventory": inventory,
            }

        except Exception as exc:
            _record_failure(journal, journal_file, "error", exc)
            try:
                _rollback_keyring_from_journal(journal, target_path)
                _checkpoint(journal, journal_file, "rolled_back")
            except Exception as rb_exc:
                _record_failure(journal, journal_file, "rollback_error", rb_exc)
            raise


def rollback_keyring(
    *,
    target_dir: Path | None = None,
    state_dir: Path | None = None,
) -> dict[str, object]:
    """Reverte supervisão systemd do keyring para legado sem recriar containers."""
    state_path, target_path = _resolve_paths("", target_dir, state_dir)
    c_name = _keyring_container_name()
    unit_name = _keyring_unit_name()
    journal_file = state_path / "keyring-journal.json"

    with _AdoptionLock(state_path, "keyring", create=False):
        if not journal_file.is_file():
            raise FileNotFoundError(f"diario de keyring ausente em {journal_file}: impossivel determinar estado anterior para rollback")

        try:
            journal = json.loads(journal_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"diario de keyring corrompido: {exc}") from exc

        _validate_journal_structure(journal, "keyring", expected_unit_name=unit_name, target_path=target_path, state_path=state_path)
        fresh_info = _inspect_keyring_container_info(c_name)
        recorded = journal["container"]
        if (recorded["id"], recorded["name"]) != (fresh_info["id"], c_name):
            raise ValueError(
                f"ID divergente para keyring: registrado {recorded['name']}/{recorded['id']}, atual {c_name}/{fresh_info['id']}"
            )

        try:
            _rollback_keyring_from_journal(journal, target_path)
        except Exception as exc:
            _record_failure(journal, journal_file, "error", exc)
            raise

        _checkpoint(journal, journal_file, "rolled_back")
        return {"status": "rolled_back", "component": "keyring"}
