"""cli/asb/doctor.py — diagnostica o ambiente e nomeia a correcao.

Regra: toda linha de falha diz o COMANDO exato a executar. "Algo esta errado"
nao ajuda ninguem as 2h da manha, e a §16.1 exige que uma maquina nova seja
recuperavel sem adivinhacao.

Tarefa 5 (decomposicao de modulos): este arquivo so COMPOE. A coleta de cada
checagem estruturada vive em `cli/asb/diagnostics/checks.py` (dados, nunca
imprime); a apresentacao em texto/JSON e a politica de codigo de saida vivem
em `cli/asb/diagnostics/report.py`. `diagnose()` decide QUANDO e EM QUE ORDEM
cada checagem roda (a mesma ordem de sempre) e monta o pacote final; `doctor()`
chama `diagnose()`, renderiza uma unica vez e devolve o codigo agregado.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .diagnostics import checks, report
from .lifecycle import check_keyring_service


def diagnose(root: Path) -> dict[str, Any]:
    """Coleta diagnóstico tipado com schemaVersion 1 e separação de infraestrutura e provedores."""
    check_results: list[checks.CheckResult] = []

    # 1. podman instalado
    podman_installed = checks.check_podman_installed()
    check_results.append(podman_installed)

    # 2. versao do podman
    if podman_installed.healthy:
        check_results.append(checks.check_podman_version())

    # 3. python >= 3.11
    check_results.append(checks.check_python_version())

    # 4. git instalado
    check_results.append(checks.check_git_installed())

    # 5. imagem base
    check_results.append(checks.check_image())

    # 6. volume credenciais
    check_results.append(checks.check_credentials_volume())

    # 7. volume toolcache
    check_results.append(checks.check_toolcache_volume())

    # 8. Secret Service
    #
    # `check_keyring_service` continua vinculado por NOME LIVRE
    # (`from .lifecycle import check_keyring_service` acima) e chamado aqui
    # dentro de `diagnose()`, que continua neste modulo — por isso
    # `mock.patch("asb.doctor.check_keyring_service", ...)` (usado em
    # `tests/unit/test_public_contracts.py`) continua interceptando sem
    # nenhum ajuste. Ver AGENTS.md / o relatorio da Tarefa 1 para o porque.
    keyring_ok, keyring_label, keyring_fix = check_keyring_service()
    check_results.append(checks.CheckResult(
        name="keyring_service", healthy=keyring_ok, label=keyring_label,
        remediation=keyring_fix,
    ))

    # 9. Emenda A: drop-in legado ausente, espera por rede, produtores alheios
    check_results.append(checks.check_project_dropin_absent())
    check_results.append(checks.check_network_gate())
    check_results.append(checks.check_netns_producers_third_party())

    # 10. guards
    for agent in ("claude", "codex", "agy"):
        check_results.append(checks.check_guard(agent, root))

    # 11. asb-agent cli
    check_results.append(checks.check_cli_guard(root))

    # 12. broker docker (opcional)
    check_results.append(checks.check_docker_broker())

    # 12b. interface web (Tarefa 7, Emenda F): seis checagens se a unidade
    # ja foi instalada, ou uma unica linha informativa se nunca foi — essa
    # linha unica mantem este `doctor` verde num host que nao usa a web.
    check_results.extend(checks.collect_web_checks(root))

    # 13. tool drifts (informativo)
    for tool, label in checks.CONTEXT_TOOLS.items():
        drift = checks.check_tool_drift(tool, label)
        if drift is not None:
            d_ok, d_label, d_fix = drift
            check_results.append(checks.CheckResult(
                name=f"drift_{tool}", healthy=True, label=d_label,
                remediation=d_fix,
            ))

    # 14. workspaces
    workspaces = checks.collect_workspaces(root)

    infra_healthy = (report.aggregate_exit_code(check_results) == 0
                      and all(ws["healthy"] for ws in workspaces))

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
            "checks": [cr.to_dict() for cr in check_results],
            "workspaces": workspaces,
        },
        "providers": providers,
    }


def doctor(root: Path, as_json: bool = False) -> int:
    diag = diagnose(root)

    if as_json:
        print(report.render_json(diag))
        return 0 if diag["healthy"] else 1

    print(report.render_text(diag), end="")
    return report.text_exit_code(diag)
