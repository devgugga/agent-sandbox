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

from typing import Any

from . import podman
from .lifecycle import (
    CREDENTIALS_VOLUME,
    TOOLCACHE_VOLUME,
    IMAGE,
    check_keyring_service,
    names,
)
from .profile import load_profile


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


def diagnose(root: Path) -> dict[str, Any]:
    """Coleta diagnóstico tipado com schemaVersion 1 e separação de infraestrutura e provedores."""
    checks: list[dict[str, Any]] = []
    infra_healthy = True

    # 1. podman instalado
    has_podman = shutil.which("podman") is not None
    checks.append({
        "name": "podman_installed",
        "healthy": has_podman,
        "label": "podman instalado",
        "remediation": "" if has_podman else "instale o podman (>= 4.0)",
    })
    infra_healthy &= has_podman

    # 2. versao do podman
    if has_podman:
        version = podman.out("--version").split()[-1]
        major = int(version.split(".")[0])
        podman_v_ok = major >= 4
        checks.append({
            "name": "podman_version",
            "healthy": podman_v_ok,
            "label": f"podman {version} (>= 4.0)",
            "remediation": "" if podman_v_ok else "atualize: --internal e resolucao por nome exigem 4+",
        })
        infra_healthy &= podman_v_ok

    # 3. python >= 3.11
    py_ok = sys.version_info >= (3, 11)
    checks.append({
        "name": "python_version",
        "healthy": py_ok,
        "label": f"python {sys.version.split()[0]} (>= 3.11)",
        "remediation": "" if py_ok else "tomllib e stdlib so a partir do 3.11",
    })
    infra_healthy &= py_ok

    # 4. git instalado
    git_ok = shutil.which("git") is not None
    checks.append({
        "name": "git_installed",
        "healthy": git_ok,
        "label": "git instalado",
        "remediation": "" if git_ok else "instale o git",
    })
    infra_healthy &= git_ok

    # 5. imagem base
    img_ok = podman.exists("image", IMAGE)
    checks.append({
        "name": "image",
        "healthy": img_ok,
        "label": f"imagem {IMAGE}",
        "remediation": "" if img_ok else "asb-agent build",
    })
    infra_healthy &= img_ok

    # 6. volume credenciais
    vol_cred_ok = podman.exists("volume", CREDENTIALS_VOLUME)
    checks.append({
        "name": "credentials_volume",
        "healthy": vol_cred_ok,
        "label": f"volume {CREDENTIALS_VOLUME}",
        "remediation": "" if vol_cred_ok else "asb-agent login",
    })
    infra_healthy &= vol_cred_ok

    # 7. volume toolcache
    vol_tool_ok = podman.exists("volume", TOOLCACHE_VOLUME)
    checks.append({
        "name": "toolcache_volume",
        "healthy": vol_tool_ok,
        "label": f"volume {TOOLCACHE_VOLUME}",
        "remediation": "" if vol_tool_ok else "podman volume create asb-toolcache",
    })
    infra_healthy &= vol_tool_ok

    # 8. Secret Service
    keyring_ok, keyring_label, keyring_fix = check_keyring_service()
    checks.append({
        "name": "keyring_service",
        "healthy": keyring_ok,
        "label": keyring_label,
        "remediation": keyring_fix,
    })
    infra_healthy &= keyring_ok

    # 9. podman-restart.service
    restart_res = subprocess.run(
        ["systemctl", "--user", "is-enabled", "podman-restart.service"],
        capture_output=True, text=True).stdout.strip()
    restart_ok = (restart_res == "enabled")
    checks.append({
        "name": "podman_restart_service",
        "healthy": restart_ok,
        "label": "podman-restart.service habilitado (restauracao no boot)",
        "remediation": "" if restart_ok else "systemctl --user enable podman-restart.service",
    })
    infra_healthy &= restart_ok

    # 10. guards
    guards = Path.home() / ".local" / "bin"
    for agent in ("claude", "codex", "agy"):
        link = guards / f"asb-{agent}"
        expected = root / "cli" / "asb-guard"
        guard_ok = link.is_symlink() and link.resolve() == expected
        checks.append({
            "name": f"guard_{agent}",
            "healthy": guard_ok,
            "label": f"guarda asb-{agent} aponta para este checkout",
            "remediation": "" if guard_ok else "asb-agent install-guards",
        })
        infra_healthy &= guard_ok

    # 11. asb-agent cli
    cli_link = guards / "asb-agent"
    cli_target = (root / "cli" / "asb-agent").resolve()
    cli_ok = cli_link.is_symlink() and cli_link.resolve() == cli_target
    checks.append({
        "name": "cli_guard",
        "healthy": cli_ok,
        "label": "asb-agent aponta para este checkout",
        "remediation": "" if cli_ok else "asb-agent install-guards",
    })
    infra_healthy &= cli_ok

    # 12. broker docker (opcional)
    broker = Path("/run/asb-docker/docker.sock")
    checks.append({
        "name": "docker_broker",
        "healthy": True,
        "label": 'broker do Docker (opcional; so para host_api = "read")',
        "remediation": "" if broker.is_socket() else "asb-agent install-broker",
    })

    # 13. tool drifts (informativo)
    for tool, label in CONTEXT_TOOLS.items():
        drift = tool_drift(tool, _image_version(label), _host_version(tool))
        if drift is not None:
            d_ok, d_label, d_fix = drift
            checks.append({
                "name": f"drift_{tool}",
                "healthy": True,
                "label": d_label,
                "remediation": d_fix,
            })

    # 14. workspaces
    workspaces: list[dict[str, Any]] = []
    for state in sorted((Path.home() / ".local" / "state" / "agent-sandbox").glob("*/origin")):
        ws = state.parent.name
        agent = names(ws)["agent"]
        origin_path = state.read_text().strip() if state.exists() else ""
        ws_healthy = True
        ws_status = "ok"
        ws_remediation = ""

        legacy_reason = ""
        if not podman.exists("container", agent):
            ws_healthy = True
            ws_status = "missing_container"
            ws_remediation = "asb-agent up"
        else:
            is_legacy, reason = check_legacy_agent_container(agent)
            if is_legacy:
                ws_healthy = False
                legacy_reason = reason
                ws_status = f"legacy_container: {reason}"
                ws_arg = shlex.quote(ws)
                repo_flag = f" --repo {shlex.quote(origin_path)}" if origin_path else ""
                ws_remediation = (
                    f"asb-agent pull --workspace {ws_arg} && "
                    f"asb-agent down --workspace {ws_arg} && "
                    f"asb-agent up --workspace {ws_arg}{repo_flag}"
                )
            elif podman.running(agent):
                egress_ok, egress_label, egress_fix = check_workspace_egress(ws)
                if not egress_ok:
                    ws_healthy = False
                    ws_status = egress_label
                    ws_remediation = egress_fix
                else:
                    ws_status = "running"
            else:
                ws_healthy = True
                ws_status = "stopped"
                ws_remediation = f"asb-agent resume --workspace {ws}"

        services_list: list[dict[str, Any]] = []
        if origin_path:
            toml_file = Path(origin_path) / ".agent-sandbox.toml"
            if toml_file.is_file():
                try:
                    prof = load_profile(Path(origin_path))
                    for svc in prof.services:
                        svc_container = f"asb-{ws}-svc-{svc.name}"
                        if not podman.exists("container", svc_container):
                            svc_healthy = False
                            svc_state = "missing"
                            svc_remediation = f"asb-agent resume --workspace {ws}"
                        elif not podman.running(svc_container):
                            svc_healthy = False
                            svc_state = "stopped"
                            svc_remediation = f"asb-agent resume --workspace {ws}"
                        else:
                            raw_health = podman.out(
                                "container", "inspect", svc_container, "--format", "{{.State.Health.Status}}"
                            ).strip()
                            if raw_health == "healthy":
                                svc_healthy = True
                                svc_state = "healthy"
                                svc_remediation = ""
                            elif raw_health in ("unhealthy", "starting"):
                                svc_healthy = False
                                svc_state = raw_health
                                svc_remediation = f"podman logs {svc_container}"
                            else:
                                # Sem healthcheck: fica process_running, não application_ready
                                svc_healthy = True
                                svc_state = "process_running"
                                svc_remediation = ""

                        if not svc_healthy:
                            ws_healthy = False

                        services_list.append({
                            "name": svc.name,
                            "container": svc_container,
                            "state": svc_state,
                            "healthy": svc_healthy,
                            "remediation": svc_remediation,
                        })
                except Exception:
                    pass

        infra_healthy &= ws_healthy
        workspaces.append({
            "workspace": ws,
            "healthy": ws_healthy,
            "status": ws_status,
            "legacy_reason": legacy_reason,
            "remediation": ws_remediation,
            "services": services_list,
        })

    # Provedores de autenticação (estritamente separados da infraestrutura).
    #
    # `doctor` e um diagnostico passivo: nunca executa dentro de containers
    # de workspace so para descobrir se uma conta esta logada (isso tocaria
    # workspaces do operador a cada `doctor`, incluindo os de producao).
    # A checagem REAL de conta vive em cli/asb/auth.py e roda sob pedido via
    # `asb-agent auth status --workspace <id>`. Por isso o estado aqui fica
    # "unknown" ate essa checagem rodar — e a remediacao aponta para ela, e
    # NAO mais para 'asb-agent login': login e uma acao que muta estado, e
    # 'nao sei ainda' nunca deveria virar 'va logar' por presuncao (a mesma
    # separacao de conta/rede/infraestrutura que a Tarefa A2 introduz).
    providers: dict[str, dict[str, Any]] = {
        "claude": {
            "state": "unknown",
            "healthy": True,
            "remediation": "asb-agent auth status --workspace <id> --agent claude --json",
        },
        "codex": {
            "state": "unknown",
            "healthy": True,
            "remediation": "asb-agent auth status --workspace <id> --agent codex --json",
        },
        "agy": {
            "state": "unknown",
            "healthy": True,
            "remediation": "asb-agent auth status --workspace <id> --agent agy --json",
        },
    }

    return {
        "schemaVersion": 1,
        "healthy": infra_healthy,
        "infrastructure": {
            "healthy": infra_healthy,
            "checks": checks,
            "workspaces": workspaces,
        },
        "providers": providers,
    }


def doctor(root: Path, as_json: bool = False) -> int:
    diag = diagnose(root)

    if as_json:
        print(json.dumps(diag, indent=2))
        return 0 if diag["healthy"] else 1

    print("agent-sandbox doctor")
    healthy = True

    for c in diag["infrastructure"]["checks"]:
        if c["name"] == "docker_broker":
            broker = Path("/run/asb-docker/docker.sock")
            _line(broker.is_socket(), c["label"], c["remediation"])
        elif c["name"].startswith("drift_"):
            _line(c["healthy"], c["label"], c["remediation"])
        else:
            healthy &= _line(c["healthy"], c["label"], c["remediation"])

    print("\nworkspaces:")
    for ws_info in diag["infrastructure"]["workspaces"]:
        ws = ws_info["workspace"]
        status = ws_info["status"]
        if status == "missing_container":
            print(f"  {ws}: SEM CONTAINER  ->  {ws_info['remediation']}")
        elif status.startswith("legacy_container: "):
            reason = ws_info.get("legacy_reason") or status.split(": ", 1)[1]
            healthy = False
            _line(False, f"workspace {ws}: container legado ({reason})", ws_info["remediation"])
        elif status == "stopped":
            print(f"  {ws}: parado  ->  {ws_info['remediation']}")
        elif status == "running":
            _line(True, f"{ws}: rodando (egresso ok)")
        else:
            healthy = False
            _line(False, status, ws_info["remediation"])

        for svc in ws_info["services"]:
            if svc["state"] in ("process_running", "healthy"):
                _line(True, f"{ws}: servico {svc['name']} ({svc['state']})")
            else:
                healthy = False
                _line(False, f"{ws}: servico {svc['name']} ({svc['state']})", svc["remediation"])

    return 0 if healthy else 1
