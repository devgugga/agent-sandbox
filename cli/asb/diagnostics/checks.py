"""cli/asb/diagnostics/checks.py — checagens estruturadas do `doctor`.

Cada funcao aqui devolve DADOS (um `CheckResult`, uma tupla ou uma lista,
conforme o formato ja em uso antes desta Tarefa 5) e nunca imprime nada.
Quem decide como apresentar — texto, JSON, codigo de saida agregado — e
`cli/asb/diagnostics/report.py`; quem decide QUANDO e EM QUE ORDEM rodar cada
checagem e `cli/asb/doctor.py`.

`CheckResult(name, healthy, label, remediation)` e a forma frozen que este
modulo produz para os itens da lista `infrastructure.checks` do relatorio.
NOTA (achado empirico, nao um requisito do brief da Tarefa 5): o brief
ilustra a interface como `CheckResult(name, state, evidence, remediation,
details)`, mas os dicionarios que `diagnose()` sempre montou usam
`{name, healthy, label, remediation}` — um booleano, nao um `state`
enumeravel, e "label" no lugar de "evidence". Trocar os nomes dos campos
exigiria reconstituir esse booleano a partir de um `state` inventado (e
depois desfazer a conversao para serializar `healthy` de volta no JSON, que
e congelado) sem nenhum ganho: pura indirecao. Seguindo o precedente ja
registrado na Tarefa 1 para `auth.py` (o exemplo do brief e ilustrativo, o
schema real e o que congela), este modulo usa os nomes de campo que os
dicionarios atuais realmente tem. `to_dict()` devolve exatamente essas
quatro chaves, nessa ordem — o schema JSON congelado."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import install, podman
from ..lifecycle import CREDENTIALS_VOLUME, TOOLCACHE_VOLUME, IMAGE, names
from ..profile import load_profile
from ..readiness import DEAD_UPLINK_REMEDIATION
from ..supervisor import network_unit_name


@dataclass(frozen=True)
class CheckResult:
    """Um item da lista `infrastructure.checks` do relatorio do doctor."""
    name: str
    healthy: bool
    label: str
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "healthy": self.healthy,
            "label": self.label,
            "remediation": self.remediation,
        }


# ---------------------------------------------------------------------------
# Ferramentas de host: presenca, versao, defasagem imagem/host.
# ---------------------------------------------------------------------------

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


def check_tool_drift(tool: str, label: str) -> tuple[bool, str, str] | None:
    """Resolve as duas versoes (label da imagem, versao do host) e chama
    `tool_drift()` — o chamador (`doctor.diagnose()`) nao precisa tocar
    `_image_version`/`_host_version` diretamente."""
    return tool_drift(tool, _image_version(label), _host_version(tool))


# ---------------------------------------------------------------------------
# Checks unitarios que hoje sao inline em diagnose(): um por item da lista
# congelada de nomes em tests/unit/test_public_contracts.py.
# ---------------------------------------------------------------------------

def check_podman_installed() -> CheckResult:
    has_podman = shutil.which("podman") is not None
    return CheckResult(
        name="podman_installed",
        healthy=has_podman,
        label="podman instalado",
        remediation="" if has_podman else "instale o podman (>= 4.0)",
    )


def check_podman_version() -> CheckResult:
    """So deve ser chamado quando `check_podman_installed().healthy` for
    verdadeiro — `podman --version` presume o binario presente."""
    version = podman.out("--version").split()[-1]
    major = int(version.split(".")[0])
    ok = major >= 4
    return CheckResult(
        name="podman_version",
        healthy=ok,
        label=f"podman {version} (>= 4.0)",
        remediation="" if ok else "atualize: --internal e resolucao por nome exigem 4+",
    )


def check_python_version() -> CheckResult:
    ok = sys.version_info >= (3, 11)
    return CheckResult(
        name="python_version",
        healthy=ok,
        label=f"python {sys.version.split()[0]} (>= 3.11)",
        remediation="" if ok else "tomllib e stdlib so a partir do 3.11",
    )


def check_git_installed() -> CheckResult:
    ok = shutil.which("git") is not None
    return CheckResult(
        name="git_installed",
        healthy=ok,
        label="git instalado",
        remediation="" if ok else "instale o git",
    )


def check_image() -> CheckResult:
    ok = podman.exists("image", IMAGE)
    return CheckResult(
        name="image",
        healthy=ok,
        label=f"imagem {IMAGE}",
        remediation="" if ok else "asb-agent build",
    )


def check_credentials_volume() -> CheckResult:
    ok = podman.exists("volume", CREDENTIALS_VOLUME)
    return CheckResult(
        name="credentials_volume",
        healthy=ok,
        label=f"volume {CREDENTIALS_VOLUME}",
        remediation="" if ok else "asb-agent login",
    )


def check_toolcache_volume() -> CheckResult:
    ok = podman.exists("volume", TOOLCACHE_VOLUME)
    return CheckResult(
        name="toolcache_volume",
        healthy=ok,
        label=f"volume {TOOLCACHE_VOLUME}",
        remediation="" if ok else "podman volume create asb-toolcache",
    )


def check_guard(agent: str, root: Path) -> CheckResult:
    """Um dos guardas `asb-claude`/`asb-codex`/`asb-agy` em ~/.local/bin."""
    guards = Path.home() / ".local" / "bin"
    link = guards / f"asb-{agent}"
    expected = root / "cli" / "asb-guard"
    ok = link.is_symlink() and link.resolve() == expected
    return CheckResult(
        name=f"guard_{agent}",
        healthy=ok,
        label=f"guarda asb-{agent} aponta para este checkout",
        remediation="" if ok else "asb-agent install-guards",
    )


def check_cli_guard(root: Path) -> CheckResult:
    guards = Path.home() / ".local" / "bin"
    cli_link = guards / "asb-agent"
    cli_target = (root / "cli" / "asb-agent").resolve()
    ok = cli_link.is_symlink() and cli_link.resolve() == cli_target
    return CheckResult(
        name="cli_guard",
        healthy=ok,
        label="asb-agent aponta para este checkout",
        remediation="" if ok else "asb-agent install-guards",
    )


def check_docker_broker() -> CheckResult:
    """Broker do Docker (opcional; so para host_api = "read").

    `healthy` e sempre True: e um recurso opcional, nunca reprova o
    diagnostico. A remediacao (vazia sse o socket existe) e a UNICA pista de
    estado real que este check carrega — o renderizador de texto usa
    `not remediation` para decidir a marca ok/FALTA sem sondar o socket de
    novo (ver `report.py`: antes desta Tarefa a marca de texto vinha de uma
    segunda chamada a `is_socket()`, redundante com esta)."""
    broker = Path("/run/asb-docker/docker.sock")
    is_socket = broker.is_socket()
    return CheckResult(
        name="docker_broker",
        healthy=True,
        label='broker do Docker (opcional; so para host_api = "read")',
        remediation="" if is_socket else "asb-agent install-broker",
    )


def check_project_dropin_absent() -> CheckResult:
    """Emenda A: o drop-in do projeto criava o namespace rootless cedo em todo boot."""
    path = install.get_dropin_path()
    try:
        exists, ours, _, _ = install.read_project_dropin()
        error = ""
    except RuntimeError as exc:
        exists, ours, error = True, True, str(exc)
    healthy = not (exists and ours)
    return CheckResult(
        name="project_dropin_absent",
        healthy=healthy,
        label=("drop-in legado do podman-restart ausente" if healthy
               else f"drop-in legado do podman-restart presente ({path})"),
        remediation="" if healthy else (
            error or f"rm {shlex.quote(str(path))} && systemctl --user daemon-reload"),
    )


def check_network_gate() -> CheckResult:
    """Estado da espera unica por rede (informativo: inativa antes do 1o workspace e normal)."""
    unit = network_unit_name()
    state = subprocess.run(
        ["systemctl", "--user", "is-active", unit],
        capture_output=True, text=True).stdout.strip() or "desconhecido"
    # `inactive` e normal antes do primeiro workspace, e `activating` e a
    # espera fazendo o trabalho dela. `failed` nao: toda unidade de workspace
    # tem Requires= nesta, entao nenhum workspace sobe enquanto ela estiver
    # assim — reportar isso como saudavel escondia a causa do `up` falhar.
    healthy = state != "failed"
    if state == "activating":
        remediation = "aguardando conectividade real do host"
    elif healthy:
        remediation = ""
    else:
        remediation = (f"journalctl --user -u {unit} && "
                       f"systemctl --user reset-failed {unit}")
    return CheckResult(
        name="network_gate",
        healthy=healthy,
        label=f"espera por rede {unit}: {state}",
        remediation=remediation,
    )


def third_party_netns_producers() -> list[str]:
    """Produtores do namespace rootless no boot que NAO sao do ASB.

    Duas classes, as que falharam no piloto: drop-ins de `podman-restart`
    alheios (o do projeto e checado por `check_project_dropin_absent`) e
    containers alheios, em rede, que o `podman-restart` sobe no boot.
    """
    producers: list[str] = []
    dropin = install.get_dropin_path()
    try:
        entries = sorted(os.listdir(dropin.parent))
    except FileNotFoundError:
        entries = []
    except OSError as exc:
        producers.append(f"desconhecido: {dropin.parent} ilegivel ({exc})")
        entries = []
    for entry in entries:
        if entry == dropin.name:
            try:
                _, ours, _, _ = install.read_project_dropin()
            except RuntimeError:
                ours = True
            if ours:
                continue
        producers.append(f"dropin:{entry}")

    try:
        res = podman.run("ps", "-a", "--filter", "should-start-on-boot=true",
                         "--format", "{{.Names}}|{{.Labels}}|{{.Networks}}",
                         check=False, capture=True)
    except podman.PodmanError as exc:
        producers.append(f"desconhecido: podman ps falhou ({exc})")
        return producers
    if res.returncode != 0:
        producers.append(f"desconhecido: podman ps falhou ({(res.stderr or '').strip() or res.returncode})")
        return producers
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        name, _, rest = line.partition("|")
        labels, _, networks = rest.partition("|")
        if "asb.workspace=" in labels or networks.strip() in ("", "none"):
            continue
        producers.append(f"container:{name}")
    return producers


def check_netns_producers_third_party() -> CheckResult:
    """Envelope de `CheckResult` em torno de `third_party_netns_producers()` —
    a checagem em si e sempre informativa (`healthy=True`; nunca reprova o
    diagnostico), exatamente como em `diagnose()` antes desta Tarefa."""
    producers = third_party_netns_producers()
    return CheckResult(
        name="netns_producers_third_party",
        healthy=True,
        label=("nenhum produtor alheio do namespace rootless no boot" if not producers
               else "produtores alheios do namespace rootless: " + ", ".join(producers)),
        remediation="" if not producers
                   else "podem inicializar o namespace antes da rede; revise-os",
    )


# ---------------------------------------------------------------------------
# Podman/runtime: containers de agente e de servico de um workspace.
# ---------------------------------------------------------------------------

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
                    DEAD_UPLINK_REMEDIATION)
    except subprocess.TimeoutExpired:
        return (False,
                f"{ws}: uplink rootless morto (timeout na sonda de egresso)",
                DEAD_UPLINK_REMEDIATION)
    except Exception as exc:
        return (False,
                f"{ws}: falha ao sondar egresso ({exc})",
                f"podman logs --tail 50 {proxy}")


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


def _service_state(ws: str, svc_container: str) -> tuple[bool, str, str]:
    """Estado de um container de servico: (saudavel, estado, remediacao)."""
    if not podman.exists("container", svc_container):
        return False, "missing", f"asb-agent resume --workspace {ws}"
    if not podman.running(svc_container):
        return False, "stopped", f"asb-agent resume --workspace {ws}"
    raw_health = podman.out(
        "container", "inspect", svc_container, "--format", "{{.State.Health.Status}}"
    ).strip()
    if raw_health == "healthy":
        return True, "healthy", ""
    if raw_health in ("unhealthy", "starting"):
        return False, raw_health, f"podman logs {svc_container}"
    # Sem healthcheck: fica process_running, nao application_ready.
    return True, "process_running", ""


# ---------------------------------------------------------------------------
# Prontidao de workspace: um item por workspace conhecido, com seus servicos.
# ---------------------------------------------------------------------------

def collect_workspaces(root: Path) -> list[dict[str, Any]]:
    """Um item por workspace com estado conhecido em disco, na mesma ordem e
    forma que `diagnose()` sempre montou (ordenado por `state.parent.name`,
    via o glob abaixo)."""
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
                except Exception as exc:
                    # Engolir isto dava `services: []` — identico a um projeto
                    # sem servico algum — com `healthy: true`. Um diagnostico
                    # nunca reporta sucesso por nao ter lido a propria entrada.
                    ws_healthy = False
                    ws_status = "perfil ilegivel"
                    ws_remediation = f"corrija {toml_file}: {exc}"
                else:
                    for svc in prof.services:
                        svc_container = f"asb-{ws}-svc-{svc.name}"
                        try:
                            svc_healthy, svc_state, svc_remediation = _service_state(
                                ws, svc_container)
                        except Exception as exc:
                            # Uma inspecao que levanta no meio abortava o laco:
                            # os servicos seguintes sumiam do relatorio sem
                            # nunca terem sido olhados.
                            svc_healthy = False
                            svc_state = f"indeterminado: {exc}"
                            svc_remediation = f"podman inspect {svc_container}"

                        if not svc_healthy:
                            ws_healthy = False

                        services_list.append({
                            "name": svc.name,
                            "container": svc_container,
                            "state": svc_state,
                            "healthy": svc_healthy,
                            "remediation": svc_remediation,
                        })

        workspaces.append({
            "workspace": ws,
            "healthy": ws_healthy,
            "status": ws_status,
            "legacy_reason": legacy_reason,
            "remediation": ws_remediation,
            "services": services_list,
        })
    return workspaces
