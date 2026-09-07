"""cli/asb/doctor.py — diagnostica o ambiente e nomeia a correcao.

Regra: toda linha de falha diz o COMANDO exato a executar. "Algo esta errado"
nao ajuda ninguem as 2h da manha, e a §16.1 exige que uma maquina nova seja
recuperavel sem adivinhacao.
"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import podman
from .lifecycle import (
    CREDENTIALS_VOLUME,
    TOOLCACHE_VOLUME,
    IMAGE,
    check_keyring_service,
    names,
)


def _line(ok: bool, label: str, fix: str = "") -> bool:
    mark = "ok  " if ok else "FALTA"
    print(f"  {mark} {label}" + ("" if ok else f"  ->  {fix}"))
    return ok


# Ferramentas de contexto instaladas na imagem -> label que declara a versao.
CONTEXT_TOOLS = {
    "rtk": "asb.rtk.version",
    "graphify": "asb.graphify.version",
}


def _host_version(tool: str) -> str | None:
    """Versao instalada no host, ou None se a ferramenta nao existe la."""
    if shutil.which(tool) is None:
        return None
    try:
        res = subprocess.run([tool, "--version"], capture_output=True,
                             text=True, timeout=5)
    except Exception:
        return None
    parts = (res.stdout or "").split()
    token = parts[-1] if parts else None
    # Uma versao comeca por digito. Saida inesperada vira None em vez de virar
    # um alerta de defasagem falso.
    return token if isinstance(token, str) and token[:1].isdigit() else None


def _image_version(label: str) -> str | None:
    """Versao declarada pelo label da imagem, sem precisar subir container."""
    try:
        out = podman.out("image", "inspect", IMAGE, "--format",
                         "{{index .Labels \"" + label + "\"}}").strip()
    except Exception:
        return None
    # podman devolve "<no value>" quando o label nao existe.
    return out if out and out != "<no value>" else None


def tool_drift(tool: str, image_version: str | None,
               host_version: str | None) -> tuple[bool, str, str] | None:
    """Compara a versao assada na imagem com a instalada no host.

    O host e a referencia: e nele que o operador atualiza a ferramenta. A
    imagem so muda com `asb-agent build`, entao a divergencia fica silenciosa
    ate alguem comparar as duas.

    Devolve None quando o host nao tem a ferramenta — nem todo host usa rtk, e
    avisar nesse caso seria ruido em vez de diagnostico.
    """
    if host_version is None:
        return None
    if image_version is None:
        return (False, f"{tool} ausente na imagem (host tem {host_version})",
                "asb-agent build")
    if image_version == host_version:
        return (True, f"{tool} {image_version} (imagem e host em sincronia)", "")
    return (False, f"{tool} {image_version} na imagem, {host_version} no host",
            "asb-agent build")


def check_workspace_egress(ws: str, target: str = "github.com", port: int = 443,
                           timeout: int = 5) -> tuple[bool, str, str]:
    """Sonda egresso a partir de dentro do container proxy do workspace.

    Distingue:
      1. egresso ok (Squid, DNS e TCP target funcionais)
      2. uplink rootless morto (Network is unreachable / pasta inativo)
      3. dominio fora da allowlist (TCP_DENIED / 403 Forbidden com rota viva)
      4. proxy parado / nao responde
    """
    proxy = names(ws)["proxy"]
    if not podman.running(proxy):
        return False, f"{ws}: proxy parado", f"asb-agent resume --workspace {ws}"

    probe_script = (
        f'resp=$(printf "CONNECT {target}:{port} HTTP/1.1\\r\\nHost: {target}:{port}\\r\\n\\r\\n" '
        f'| nc -w 2 127.0.0.1 3128 2>/dev/null | head -n 1)\n'
        f'case "$resp" in\n'
        f'  *" 200 "*)\n'
        f'    echo "OK"\n'
        f'    exit 0 ;;\n'
        f'  *" 403 "*)\n'
        f'    echo "DENIED"\n'
        f'    exit 3 ;;\n'
        f'  *)\n'
        f'    err=$(nc -z -v -w 2 1.1.1.1 53 2>&1 || true)\n'
        f'    if echo "$err" | grep -qi "Network is unreachable"; then\n'
        f'      echo "UNREACHABLE"\n'
        f'      exit 2\n'
        f'    fi\n'
        f'    if [ -z "$resp" ] && nc -z -w 2 1.1.1.1 53 >/dev/null 2>&1; then\n'
        f'      echo "SQUID_DOWN"\n'
        f'      exit 4\n'
        f'    fi\n'
        f'    echo "UPLINK_FAIL"\n'
        f'    exit 2 ;;\n'
        f'esac\n'
    )

    try:
        res = subprocess.run(
            [podman.require_binary(), "exec", proxy, "sh", "-c", probe_script],
            capture_output=True, text=True, timeout=timeout)
        stdout = res.stdout.strip()
        if res.returncode == 0 or stdout == "OK":
            return True, f"{ws}: rodando (egresso ok)", ""
        elif res.returncode == 3 or stdout == "DENIED":
            return (False,
                    f"{ws}: dominio {target} bloqueado pelo Squid (TCP_DENIED)",
                    "adicione o dominio em [network] allow")
        elif res.returncode == 4 or stdout == "SQUID_DOWN":
            return (False,
                    f"{ws}: proxy Squid nao responde na porta 3128",
                    f"asb-agent resume --workspace {ws}")
        else:
            return (False,
                    f"{ws}: uplink rootless morto (Network is unreachable)",
                    "podman unshare --rootless-netns true")
    except subprocess.TimeoutExpired:
        return (False,
                f"{ws}: uplink rootless morto (timeout na sonda de egresso)",
                "podman unshare --rootless-netns true")
    except Exception as exc:
        return (False,
                f"{ws}: falha ao sondar egresso ({exc})",
                "podman unshare --rootless-netns true")


def check_legacy_agent_container(agent: str) -> tuple[bool, str]:
    """Verifica se o container do agente cumpre o contrato do Secret Service singleton.

    Retorna (True, motivo) se for container legado ou invalido (falha fechada):
      - erro de inspecao/JSON;
      - mount /run/asb-keyring ausente;
      - mascara de tmpfs ausente em /run/asb-credentials/keyrings;
      - DBUS_SESSION_BUS_ADDRESS != unix:path=/run/asb-keyring/bus;
      - ASB_KEYRING_PASS presente no ambiente.
    Retorna (False, "") se for compativel.
    """
    try:
        raw = podman.out("container", "inspect", agent, "--format", "{{json .}}")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("inspect nao retornou um objeto JSON")
        mount_items = data.get("Mounts", []) or []
        host_config = data.get("HostConfig", {}) or {}
        config = data.get("Config", {}) or {}
        if not isinstance(mount_items, list) or not all(
            isinstance(item, dict) for item in mount_items
        ):
            raise ValueError("Mounts possui formato inesperado")
        if not isinstance(host_config, dict) or not isinstance(config, dict):
            raise ValueError("configuracao do inspect possui formato inesperado")
    except Exception as exc:
        return True, f"falha ao inspecionar container ({exc})"

    mounts = {
        m.get("Destination") or m.get("destination"): m
        for m in mount_items
        if m.get("Destination") or m.get("destination")
    }
    runtime_mount = mounts.get("/run/asb-keyring")
    if runtime_mount is None:
        return True, "mount /run/asb-keyring ausente"
    if runtime_mount.get("RW") is not False:
        return True, "mount /run/asb-keyring deve ser somente leitura"

    credentials_mount = mounts.get("/run/asb-credentials")
    if credentials_mount is None:
        return True, "mount /run/asb-credentials ausente"
    if credentials_mount.get("RW") is not True:
        return True, "mount /run/asb-credentials deve ser leitura/escrita"

    if "/run/asb-keyring-data" in mounts or "/run/asb-keyring-pass" in mounts:
        return True, "cliente possui mount privado do singleton"

    tmpfs_mounts = host_config.get("Tmpfs", {}) or {}
    if not isinstance(tmpfs_mounts, dict):
        return True, "falha ao inspecionar container (HostConfig.Tmpfs possui formato inesperado)"
    mask_options = tmpfs_mounts.get("/run/asb-credentials/keyrings")
    if not isinstance(mask_options, str):
        return True, "mascara de isolamento de keyrings ausente em /run/asb-credentials/keyrings"
    option_set = {option.strip().lower() for option in mask_options.split(",")}
    if "ro" not in option_set or "rw" in option_set or "mode=000" not in option_set:
        return True, "mascara de isolamento de keyrings deve ser tmpfs ro com mode=000"

    create_command = config.get("CreateCommand", []) or []
    if not isinstance(create_command, list):
        return True, "falha ao inspecionar container (Config.CreateCommand possui formato inesperado)"
    has_notmpcopyup = any(
        isinstance(arg, str)
        and "destination=/run/asb-credentials/keyrings" in arg
        and "notmpcopyup" in {part.strip().lower() for part in arg.split(",")}
        for arg in create_command
    )
    if not has_notmpcopyup:
        return True, "mascara de isolamento de keyrings sem notmpcopyup"

    env_list = config.get("Env", []) or []
    if not isinstance(env_list, list) or not all(isinstance(item, str) for item in env_list):
        return True, "falha ao inspecionar container (Config.Env possui formato inesperado)"
    env_dict = {}
    for item in env_list:
        if "=" in item:
            k, v = item.split("=", 1)
            env_dict[k] = v

    if env_dict.get("DBUS_SESSION_BUS_ADDRESS") != "unix:path=/run/asb-keyring/bus":
        return True, "DBUS_SESSION_BUS_ADDRESS incorreto ou ausente"

    if "ASB_KEYRING_PASS" in env_dict:
        return True, "ASB_KEYRING_PASS presente no ambiente"

    return False, ""


def doctor(root: Path) -> int:
    print("agent-sandbox doctor")
    healthy = True

    healthy &= _line(shutil.which("podman") is not None, "podman instalado",
                     "instale o podman (>= 4.0)")
    if shutil.which("podman"):
        version = podman.out("--version").split()[-1]
        major = int(version.split(".")[0])
        healthy &= _line(major >= 4, f"podman {version} (>= 4.0)",
                         "atualize: --internal e resolucao por nome exigem 4+")

    healthy &= _line(sys.version_info >= (3, 11),
                     f"python {sys.version.split()[0]} (>= 3.11)",
                     "tomllib e stdlib so a partir do 3.11")
    healthy &= _line(shutil.which("git") is not None, "git instalado",
                     "instale o git")

    healthy &= _line(podman.exists("image", IMAGE), f"imagem {IMAGE}",
                     "asb-agent build")
    healthy &= _line(podman.exists("volume", CREDENTIALS_VOLUME),
                     f"volume {CREDENTIALS_VOLUME}", "asb-agent login")
    healthy &= _line(podman.exists("volume", TOOLCACHE_VOLUME),
                     f"volume {TOOLCACHE_VOLUME}", "podman volume create asb-toolcache")

    ok, label, fix = check_keyring_service()
    healthy &= _line(ok, label, fix)

    enabled = subprocess.run(
        ["systemctl", "--user", "is-enabled", "podman-restart.service"],
        capture_output=True, text=True).stdout.strip()
    healthy &= _line(enabled == "enabled",
                     "podman-restart.service habilitado (restauracao no boot)",
                     "systemctl --user enable podman-restart.service")

    guards = Path.home() / ".local" / "bin"
    for agent in ("claude", "codex", "agy"):
        link = guards / f"asb-{agent}"
        expected = root / "cli" / "asb-guard"
        # Checkout movido: o link aponta para um caminho que nao existe mais.
        # E o modo de falha da §16.1, e aqui ele e visivel em vez de silencioso.
        healthy &= _line(link.is_symlink() and link.resolve() == expected,
                         f"guarda asb-{agent} aponta para este checkout",
                         "asb-agent install-guards")

    # Sem este link o CLI so roda de dentro do checkout. O v1 nao tinha essa
    # limitacao, e a ausencia dele e silenciosa: o operador so descobre quando
    # digita `asb-agent` em outro diretorio e nao acontece nada.
    cli_link = guards / "asb-agent"
    cli_target = (root / "cli" / "asb-agent").resolve()
    healthy &= _line(cli_link.is_symlink() and cli_link.resolve() == cli_target,
                     "asb-agent aponta para este checkout",
                     "asb-agent install-guards")

    broker = Path("/run/asb-docker/docker.sock")
    _line(broker.is_socket(),
          'broker do Docker (opcional; so para host_api = "read")',
          "asb-agent install-broker")

    # Defasagem e informativa, nao falha: a imagem continua utilizavel com a
    # versao antiga. O que nao pode acontecer e a divergencia ficar invisivel.
    for tool, label in CONTEXT_TOOLS.items():
        drift = tool_drift(tool, _image_version(label), _host_version(tool))
        if drift is not None:
            _line(*drift)

    print("\nworkspaces:")
    for state in sorted((Path.home() / ".local" / "state" /
                         "agent-sandbox").glob("*/origin")):
        ws = state.parent.name
        agent = names(ws)["agent"]
        if not podman.exists("container", agent):
            print(f"  {ws}: SEM CONTAINER  ->  asb-agent up")
        else:
            is_legacy, reason = check_legacy_agent_container(agent)
            if is_legacy:
                healthy = False
                origin_path = state.read_text().strip() if state.exists() else ""
                ws_arg = shlex.quote(ws)
                repo_flag = f" --repo {shlex.quote(origin_path)}" if origin_path else ""
                remediation = f"asb-agent pull --workspace {ws_arg} && asb-agent down --workspace {ws_arg} && asb-agent up --workspace {ws_arg}{repo_flag}"
                _line(False, f"workspace {ws}: container legado ({reason})", remediation)
            elif podman.running(agent):
                egress_ok, label, fix = check_workspace_egress(ws)
                healthy &= _line(egress_ok, label, fix)
            else:
                print(f"  {ws}: parado  ->  asb-agent resume --workspace {ws}")

    return 0 if healthy else 1
