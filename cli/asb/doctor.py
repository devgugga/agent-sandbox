"""cli/asb/doctor.py — diagnostica o ambiente e nomeia a correcao.

Regra: toda linha de falha diz o COMANDO exato a executar. "Algo esta errado"
nao ajuda ninguem as 2h da manha, e a §16.1 exige que uma maquina nova seja
recuperavel sem adivinhacao.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from . import podman
from .lifecycle import CREDENTIALS_VOLUME, TOOLCACHE_VOLUME, IMAGE, names


def _line(ok: bool, label: str, fix: str = "") -> bool:
    mark = "ok  " if ok else "FALTA"
    print(f"  {mark} {label}" + ("" if ok else f"  ->  {fix}"))
    return ok


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

    broker = Path("/run/asb-docker/docker.sock")
    _line(broker.is_socket(),
          'broker do Docker (opcional; so para host_api = "read")',
          "asb-agent install-broker")

    print("\nworkspaces:")
    for state in sorted((Path.home() / ".local" / "state" /
                         "agent-sandbox").glob("*/origin")):
        ws = state.parent.name
        agent = names(ws)["agent"]
        if not podman.exists("container", agent):
            print(f"  {ws}: SEM CONTAINER  ->  asb-agent up")
        elif podman.running(agent):
            egress_ok, label, fix = check_workspace_egress(ws)
            healthy &= _line(egress_ok, label, fix)
        else:
            print(f"  {ws}: parado  ->  asb-agent resume --workspace {ws}")

    return 0 if healthy else 1
