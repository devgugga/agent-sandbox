"""cli/asb/keyring.py — singleton de Secret Service (asb-keyring).

Extraido de cli/asb/lifecycle.py (Tarefa A2) sem mudar armazenamento nem
comportamento: mesmos volumes, mesmo passfile, mesmo contrato de mounts,
mesma logica de upgrade automatico e mesmas mensagens de diagnostico.

IMAGE, CREDENTIALS_VOLUME e ensure_credentials_volume continuam em
lifecycle.py (nao sao conceitos exclusivos do keyring: IMAGE e a imagem base
de todo o sistema, e o volume de credenciais tambem serve claude/codex em
texto plano). Este modulo os importa tardiamente, dentro das funcoes que
precisam deles, para evitar import circular com lifecycle.py — o mesmo
padrao ja usado em readiness.py.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

from . import podman

CONFIG = (
    Path(os.environ["ASB_CONFIG_ROOT"])
    if "ASB_CONFIG_ROOT" in os.environ
    else Path(os.path.expanduser("~")) / ".config" / "agent-sandbox"
)
KEYRING_CONTAINER = "asb-keyring"
KEYRING_RUNTIME_VOLUME = "asb-keyring-runtime"
KEYRING_DATA_VOLUME = "asb-keyring-data"
KEYRING_BUS = "/run/asb-keyring/bus"
KEYRING_PASS = CONFIG / "keyring.pass"
KEYRING_SCHEMA = "2"


def _inspect_keyring_container(container: str, timeout: float | None = None) -> tuple[str, dict[str, dict[str, object]]]:
    """Retorna o schema e os mounts reais do singleton, indexados por destino."""
    try:
        raw = podman.out("container", "inspect", container, "--format", "{{json .}}", timeout=timeout)
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
    from .lifecycle import CREDENTIALS_VOLUME

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


def check_keyring_service(container: str | None = None, timeout: float | None = None) -> tuple[bool, str, str]:
    """Verifica a saude do servico de keyring singleton sem mutacao.

    Distingue:
      1. container ausente: 'container asb-keyring'
      2. container parado: 'asb-keyring parado'
      3. schema desatualizado: 'schema do Secret Service ... desatualizado'
      4. contrato de mounts violado: 'contrato de mounts do Secret Service violado'
      5. socket ausente: 'socket do Secret Service (asb-keyring)'
      6. Secret Service sem resposta: 'Secret Service sem resposta (asb-keyring)'
      7. saudavel: 'Secret Service (asb-keyring)'
    Falhas de INFRAESTRUTURA identificadas com precisao (podman ausente,
    container ausente/parado, schema desatualizado, contrato de mounts
    violado, socket ausente, Secret Service sem resposta) apontam para
    reparo de infraestrutura via podman — nunca para 'asb-agent login':
    keyring e um singleton compartilhado sem dono de conta, e login e uma
    acao que muta a CONTA de um fornecedor, nao a infraestrutura local. So o
    fallback generico de excecao inesperada (falha nao prevista durante a
    propria checagem) ainda aponta para 'asb-agent login', por falta de um
    diagnostico mais especifico nesse caso.
    """
    name = container or os.environ.get("ASB_KEYRING_CONTAINER", KEYRING_CONTAINER)
    if shutil.which("podman") is None:
        return (False, f"container {name}",
                "instale/verifique o podman; o container e criado "
                "automaticamente ao preparar um workspace")

    try:
        if not podman.exists("container", name, timeout=timeout):
            return (False, f"container {name}",
                    "prepare um workspace para criar o container "
                    "automaticamente, ou verifique 'asb-agent doctor'")
        if not podman.running(name, timeout=timeout):
            # Pela unidade: `podman start` por fora deixa asb-keyring.service
            # inativa e sem o reinicio do systemd.
            return (False, f"{name} parado",
                    f"systemctl --user restart {name}.service")

        schema, mounts = _inspect_keyring_container(name, timeout=timeout)
        if schema != KEYRING_SCHEMA:
            return (False, f"schema do Secret Service ({name}) desatualizado ({schema or 'legado'})",
                    f"recrie o container: podman rm -f {name} "
                    "(schema e atualizado automaticamente ao preparar um workspace)")

        contract_issue = _keyring_mount_contract_issue(mounts)
        if contract_issue:
            return (False, f"contrato de mounts do Secret Service violado ({name}): {contract_issue}",
                    f"recrie o container: podman rm -f {name} "
                    "(contrato de mounts e restaurado automaticamente ao preparar um workspace)")

        sock_check = podman.run(
            "exec", "-u", "1000", name,
            "test", "-S", KEYRING_BUS,
            check=False,
            timeout=timeout,
        )
        sock_rc = getattr(sock_check, "returncode", 1) if sock_check is not None else 1
        if sock_rc != 0:
            return (False, f"socket do Secret Service ({name})",
                    f"reinicie o servico: podman restart {name}")

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
            timeout=timeout,
        )
        secrets_rc = getattr(secrets_check, "returncode", 1) if secrets_check is not None else 1
        if secrets_rc != 0:
            # Mesma classe de falha do socket ausente (servico dentro do
            # container nao responde): mesma remediacao de infraestrutura.
            return (False, f"Secret Service sem resposta ({name})",
                    f"reinicie o servico: podman restart {name}")

        return True, f"Secret Service ({name})", ""
    except Exception as exc:
        return False, f"Secret Service ({name}): {exc}", "asb-agent login"


def _restart_policy(container: str) -> str:
    """Politica de reinicio do Podman do container (vazio quando nao declarada)."""
    return podman.out(
        "inspect", container, "--format", "{{.HostConfig.RestartPolicy.Name}}").strip()


def ensure_keyring_service(runtime_dir: Path, timeout: float = 180.0) -> str:
    """Garante o keyring singleton supervisionado pelo systemd de usuario (Emenda A §5).

    O container nasce com `--restart=no`; quem o inicia e reinicia e a unidade
    `<container>.service`, cuja sonda `runtime_check --role keyring` so deixa a
    unidade ativa com o Secret Service respondendo.

    Container de schema 1, com contrato de mounts legado ou ainda com politica
    de reinicio do Podman (o runtime legacy) e recriado. SO o container sai:
    volumes e passfile ficam intactos, entao nenhuma credencial e apagada.
    A existencia e consultada uma vez so; depois do `rm` o estado segue pela
    variavel `present`.
    """
    from . import supervisor
    from .lifecycle import IMAGE, ensure_credentials_volume

    container = os.environ.get("ASB_KEYRING_CONTAINER", KEYRING_CONTAINER)
    present = podman.exists("container", container)
    if present:
        schema, mounts = _inspect_keyring_container(container)
        if schema not in ("", "1", KEYRING_SCHEMA):
            raise podman.PodmanError(
                f"container '{container}' possui schema incompativel ({schema}). "
                f"Remova-o com 'podman rm -f {container}' e execute 'asb-agent login'."
            )
        needs_recreate = (
            schema in ("", "1")
            or bool(_keyring_mount_contract_issue(mounts))
            or _restart_policy(container) != "no"
        )
        if needs_recreate:
            podman.run("rm", "-f", container, check=False)
            present = False

    if not present:
        if not podman.exists("image", IMAGE):
            raise podman.PodmanError(
                f"imagem {IMAGE} ausente; execute 'asb-agent build'")
        pass_file = ensure_keyring_pass()
        cred_vol = ensure_credentials_volume()
        keyring_data_vol = ensure_keyring_data_volume()
        run_vol = ensure_keyring_runtime_volume()
        podman.run(
            "create", "--name", container,
            "--label", f"asb.keyring.schema={KEYRING_SCHEMA}",
            "--network", "none",
            "--restart", "no",
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

    unit_name = supervisor.install_keyring_unit(container, runtime_dir).name
    try:
        subprocess.run(["systemctl", "--user", "enable", unit_name],
                       check=True, capture_output=True, text=True)
        subprocess.run(["systemctl", "--user", "start", unit_name],
                       check=True, capture_output=True, text=True, timeout=timeout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise podman.PodmanError(
            f"servico de keyring '{unit_name}' nao ficou pronto; veja "
            f"'systemctl --user status {unit_name}' e "
            f"'journalctl --user -u {unit_name}'"
        ) from exc
    return container
