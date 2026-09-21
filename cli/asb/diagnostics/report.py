"""cli/asb/diagnostics/report.py — apresentacao (texto/JSON) e politica de
codigo de saida do `doctor`, separadas da coleta em `checks.py`.

NOTA (achado empirico, nao um requisito do brief da Tarefa 5): o brief
ilustra `render_text(results)`/`render_json(results)` recebendo so a lista de
`CheckResult`. Na pratica, tanto o texto quanto o JSON de hoje tambem
precisam da secao `workspaces` (e o JSON, alem disso, de `schemaVersion`,
`healthy` de topo e `providers`) — nenhuma das duas saidas e reconstituivel
so a partir da lista de checks. As duas funcoes abaixo recebem o pacote
completo que `doctor.py` monta (o mesmo dicionario que `diagnose()` sempre
devolveu), preservando o schema JSON e o texto byte a byte; ver o relatorio
da Tarefa 5 para o detalhe.
"""
from __future__ import annotations

import json
from typing import Any

from .checks import CheckResult

# Nomes que hoje NUNCA entram no agregado de saude de infraestrutura do modo
# --json (`diagnose()`'s `infra_healthy`): sao informativos, com `healthy`
# fixo em True (docker_broker, drift_*, netns_producers_third_party) ou,
# no caso de `network_gate`, um achado empirico preexistente (ver
# `_TEXT_EXCLUDED_NAMES` abaixo e o relatorio da Tarefa 5) — NAO um requisito
# do brief, preservado tal como estava, nao corrigido.
_JSON_EXCLUDED_NAMES = frozenset({
    "network_gate", "docker_broker", "netns_producers_third_party",
})
_DRIFT_PREFIX = "drift_"

# Nomes excluidos do agregado de saude do modo texto. Divergem dos do JSON:
# `network_gate` conta aqui (e nao conta no JSON) porque o laco de impressao
# original nunca teve um `if c["name"] == "network_gate": continue` — so
# tratava `docker_broker` e `drift_*` como especiais. Ver o relatorio da
# Tarefa 5, secao "achado empirico": os dois modos ja divergiam antes desta
# Tarefa, e este modulo preserva a divergencia em vez de unifica-la.
_TEXT_EXCLUDED_NAMES = frozenset({"docker_broker"})


def _line(lines: list[str], ok: bool, label: str, fix: str = "") -> bool:
    """Primitiva de renderizacao de uma linha de texto do doctor. Escreve em
    `lines` (em vez de imprimir) para que `render_text` devolva uma `str`."""
    mark = "ok  " if ok else "FALTA"
    lines.append(f"  {mark} {label}" + ("" if ok else f"  ->  {fix}"))
    return ok


def render_text(diag: dict[str, Any]) -> str:
    """Texto identico ao que `doctor()` imprimia antes desta Tarefa.

    Caso especial preservado: `docker_broker` tem `healthy` sempre fixo em
    True no dado coletado (e um recurso opcional, nunca reprova o
    diagnostico) — a marca ok/FALTA exibida vem de `not remediation`
    (remediation e vazia sse o socket existe), a MESMA informacao que o
    codigo pre-Tarefa 5 obtinha sondando `Path(...).is_socket()` uma segunda
    vez aqui. Essa segunda sonda foi removida: `check_docker_broker()` em
    `checks.py` ja sondou o socket uma unica vez para decidir a
    remediacao, e este renderizador reaproveita o resultado em vez de
    sondar de novo (Passo 4: nenhuma sonda duplicada)."""
    lines: list[str] = ["agent-sandbox doctor"]

    for c in diag["infrastructure"]["checks"]:
        if c["name"] == "docker_broker":
            _line(lines, not c["remediation"], c["label"], c["remediation"])
        else:
            _line(lines, c["healthy"], c["label"], c["remediation"])

    lines.append("")
    lines.append("workspaces:")
    for ws_info in diag["infrastructure"]["workspaces"]:
        ws = ws_info["workspace"]
        status = ws_info["status"]
        if status == "missing_container":
            lines.append(f"  {ws}: SEM CONTAINER  ->  {ws_info['remediation']}")
        elif status.startswith("legacy_container: "):
            reason = ws_info.get("legacy_reason") or status.split(": ", 1)[1]
            _line(lines, False, f"workspace {ws}: container legado ({reason})",
                  ws_info["remediation"])
        elif status == "stopped":
            lines.append(f"  {ws}: parado  ->  {ws_info['remediation']}")
        elif status == "running":
            _line(lines, True, f"{ws}: rodando (egresso ok)")
        else:
            _line(lines, False, status, ws_info["remediation"])

        for svc in ws_info["services"]:
            if svc["state"] in ("process_running", "healthy"):
                _line(lines, True, f"{ws}: servico {svc['name']} ({svc['state']})")
            else:
                _line(lines, False,
                      f"{ws}: servico {svc['name']} ({svc['state']})",
                      svc["remediation"])

    return "\n".join(lines) + "\n"


def render_json(diag: dict[str, Any]) -> str:
    """JSON identico ao que `doctor(as_json=True)` imprimia antes desta
    Tarefa: `json.dumps` do pacote completo, sem reordenar nem filtrar
    chaves."""
    return json.dumps(diag, indent=2)


def aggregate_exit_code(results: list[CheckResult]) -> int:
    """Codigo de saida agregado do modo --json, replicando a acumulacao
    seletiva que `diagnose()` sempre fez (`infra_healthy &= ...` pulando
    deliberadamente `network_gate`, `docker_broker`, `drift_*` e
    `netns_producers_third_party` — os quatro sao informativos).

    R26: um conjunto VAZIO de checks e sempre falha de infraestrutura — nunca
    reporta saudavel por nao ter examinado nada. `doctor()` nunca chama esta
    funcao com uma lista vazia (`check_podman_installed()` e sempre o
    primeiro item, incondicional — ver `checks.py`), entao este caso nunca e
    alcancado em producao; a asercao vale so para esta funcao pura, por
    contrato, nao como caracterizacao de um caminho hoje alcancavel."""
    if not results:
        return 1
    healthy = all(
        r.healthy for r in results
        if r.name not in _JSON_EXCLUDED_NAMES and not r.name.startswith(_DRIFT_PREFIX)
    )
    return 0 if healthy else 1


def text_exit_code(diag: dict[str, Any]) -> int:
    """Codigo de saida agregado do modo texto.

    NAO esta na lista de interfaces do brief (que so nomeia
    `aggregate_exit_code`). E necessaria porque o `doctor()` de hoje ja
    computa dois codigos DIFERENTES a partir do MESMO diagnostico: o `healthy`
    de JSON exclui `network_gate` do agregado (um `&=` que falta em
    `diagnose()`), mas o laco de impressao em texto inclui `network_gate` (so
    trata `docker_broker` e `drift_*` como especiais). Com a unica espera de
    rede em `failed`, `doctor(as_json=True)` devolve 0 e `doctor()` (texto)
    devolve 1 — verificado empiricamente antes desta Tarefa. E um bug
    preexistente, nao desta Tarefa: preservado aqui como uma segunda funcao
    de agregacao em vez de unificado, porque unificar mudaria o codigo de
    saida de um dos dois modos. Ver o relatorio da Tarefa 5."""
    healthy = True
    for c in diag["infrastructure"]["checks"]:
        if c["name"] in _TEXT_EXCLUDED_NAMES or c["name"].startswith(_DRIFT_PREFIX):
            continue
        healthy = healthy and c["healthy"]

    for ws_info in diag["infrastructure"]["workspaces"]:
        status = ws_info["status"]
        if status.startswith("legacy_container: "):
            healthy = False
        elif status not in ("missing_container", "stopped", "running"):
            healthy = False
        for svc in ws_info["services"]:
            if svc["state"] not in ("process_running", "healthy"):
                healthy = False

    return 0 if healthy else 1
