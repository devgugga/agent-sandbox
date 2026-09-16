"""tests/integration/collect_boot_evidence.py — evidencia por boot (T2).

SOMENTE LEITURA. Nao cria estado, nao inicia login e NUNCA chama
`auth verify`: o orcamento de A4 e de uma chamada real por fornecedor, sem
retry, e um coletor que roda a cada boot o queimaria tres vezes por boot. O
resultado agregado de autenticacao vem de `auth status --json`, documentado
como "nunca inicia login".

A selecao de campos e uma ALLOWLIST POSITIVA, nunca uma denylist. O manifesto
`runtime.json` carrega `ssh_key` e, conforme o ambiente, um numero VARIAVEL de
chaves `ASB_*` — entre elas `ASB_KEYRING_PASS_FILE`, que aponta para a
passphrase do keyring. Uma denylist deixaria passar em silencio toda chave
nova que o lifecycle passasse a gravar; por isso cada campo aqui e escolhido
pelo nome, e o que nao foi escolhido nao existe no relatorio.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "cli") not in sys.path:
    sys.path.insert(0, str(ROOT / "cli"))

SCHEMA = 1

BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")

# Campos do manifesto que entram no relatorio. Nada fora desta tupla e copiado.
MANIFEST_FIELDS: tuple[str, ...] = ("workspace", "runtime_type")

# Campos de cada container que entram no relatorio.
CONTAINER_FIELDS: tuple[str, ...] = ("name", "id", "unit")

_TIMEOUT = 15


def _run(args: list[str], timeout: int = _TIMEOUT) -> str:
    """Executa um comando de leitura e devolve stdout, ou "" em qualquer falha."""
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _run_capture(args: list[str], timeout: int = _TIMEOUT) -> str:
    """Como `_run`, mas devolve stdout MESMO com codigo de saida != 0.

    `auth status` sai com codigo 2 quando algum fornecedor nao esta
    autenticado — e esse e exatamente o estado que o piloto precisa
    registrar. Descartar o stdout pelo codigo de saida apagaria a evidencia.
    """
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def _boot_id() -> str:
    try:
        return BOOT_ID_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _state_dir(workspace: str) -> Path:
    """Mesmo caminho que `workspace.layout_for` deriva, sem precisar do repo.

    Nao cria o diretorio: o coletor e somente leitura.
    """
    return Path.home() / ".local" / "state" / "agent-sandbox" / workspace


def _manifest(workspace: str) -> dict:
    try:
        raw = (_state_dir(workspace) / "runtime.json").read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _containers(manifest: dict) -> dict:
    """Extrai nome, id e unidade de cada container. Nunca `podman inspect`."""
    out: dict[str, dict] = {}
    declared = manifest.get("containers")
    if not isinstance(declared, dict):
        return out
    for role, entry in declared.items():
        if not isinstance(entry, dict):
            continue
        out[str(role)] = {f: entry.get(f, "") for f in CONTAINER_FIELDS}
    return out


def _versions() -> dict:
    image = _run(["podman", "image", "inspect", "agent-sandbox:latest",
                  "--format", "{{.Id}}"])
    return {
        "podman": _run(["podman", "--version"]),
        "systemd": _run(["systemctl", "--version"]).splitlines()[0]
        if _run(["systemctl", "--version"]) else "",
        "python": sys.version.split()[0],
        "image": image[:19] if image else "",
    }


def _systemd_state(containers: dict) -> dict:
    """Estado de cada unidade. `is-active` sai com codigo != 0 quando inativa,
    entao o retorno e lido do stdout e nao do codigo."""
    states: dict[str, str] = {}
    for role, entry in containers.items():
        unit = entry.get("unit") or ""
        if not unit:
            continue
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", unit],
                capture_output=True, text=True, timeout=_TIMEOUT)
            states[role] = result.stdout.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            states[role] = "unknown"
    return states


def _port(containers: dict) -> int | None:
    agent = containers.get("agent", {}).get("name") or ""
    if not agent:
        return None
    mapping = _run(["podman", "port", agent, "22"])
    if not mapping:
        return None
    try:
        return int(mapping.splitlines()[0].rsplit(":", 1)[-1])
    except ValueError:
        return None


def _network(workspace: str) -> list[dict]:
    """Etapas de rede, do conjunto de probes de prontidao (somente leitura)."""
    try:
        from asb import readiness
    except ImportError:
        return []
    try:
        probes = readiness.probe_workspace(workspace)
    except Exception:
        return []
    return [
        {
            "component": p.component,
            "state": p.state,
            "code": p.code,
            "elapsed_ms": p.elapsed_ms,
        }
        for p in probes
    ]


def _auth(workspace: str) -> dict:
    """Resultado AGREGADO de autenticacao, via `auth status --json`.

    Nunca `auth verify`: chamada real ao fornecedor, orcamento de 1 por
    fornecedor em A4. So o estado por fornecedor entra; `evidence` e
    `remediation` ficam de fora porque descrevem o conteudo da credencial.
    """
    raw = _run_capture([str(ROOT / "cli" / "asb-agent"), "auth", "status",
                        "--workspace", workspace, "--json"], timeout=60)
    if not raw:
        return {"aggregate": "unknown", "providers": {}}
    try:
        report = json.loads(raw)
    except ValueError:
        return {"aggregate": "unknown", "providers": {}}
    providers = {
        str(r.get("provider", "")): str(r.get("state", "unknown"))
        for r in report.get("results", [])
        if isinstance(r, dict)
    }
    states = set(providers.values())
    if not providers:
        aggregate = "unknown"
    elif states == {"authenticated"}:
        aggregate = "authenticated"
    elif "unauthenticated" in states:
        # Um deslogado DEFINIDO domina um "unknown": o agregado nao pode
        # esconder a falha real atras da incerteza de outro fornecedor.
        aggregate = "incomplete"
    elif "unknown" in states:
        aggregate = "unknown"
    else:
        aggregate = "incomplete"
    return {"aggregate": aggregate, "providers": providers}


def collect(workspace: str) -> dict:
    """Relatorio de evidencia de um boot, para o workspace informado.

    Tolera workspace inexistente: devolve a forma completa com valores vazios,
    porque o primeiro boot de um piloto e medido antes de existir manifesto.
    """
    manifest = _manifest(workspace)
    containers = _containers(manifest)

    report = {
        "schema": SCHEMA,
        "boot_id": _boot_id(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workspace": workspace,
        "versions": _versions(),
        "containers": containers,
        "port": _port(containers),
        "systemd": _systemd_state(containers),
        "network": _network(workspace),
        "auth": _auth(workspace),
    }
    for field in MANIFEST_FIELDS:
        if field == "workspace":
            continue
        report[field] = manifest.get(field, "")
    return report


def main() -> int:
    if len(sys.argv) != 2:
        print("uso: collect_boot_evidence.py <workspace>", file=sys.stderr)
        return 2
    print(json.dumps(collect(sys.argv[1]), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
