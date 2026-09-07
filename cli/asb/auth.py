"""cli/asb/auth.py — status de CONTA por fornecedor (Tarefa A2).

Separa tres coisas que o `doctor` v1 misturava: se a CONTA de um fornecedor
esta autenticada, se a REDE alcanca o fornecedor, e se a INFRAESTRUTURA local
(keyring, containers) esta saudavel. Este modulo responde SOMENTE a primeira
pergunta. Rede e infraestrutura ja tem seus proprios sensores dedicados
(cli/asb/readiness.py, cli/asb/keyring.py).

Diagnostico puro: nenhuma funcao aqui inicia login, faz logout ou envia
prompt. `check_status`/`status` apenas LEEM o estado corrente do fornecedor,
executando como uid 1000 com o mesmo ambiente do workspace e timeout
limitado (10s) — o mesmo perfil de execucao usado pelas demais sondas.

Um retorno "authenticated" aqui prova que o comando de status do fornecedor
respondeu como autenticado agora; nao e prova de que uma chamada real foi
aceita pelo servidor remoto (isso cabe a `verify`, Tarefa A4).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from . import lifecycle, podman


@dataclass(frozen=True)
class AuthResult:
    provider: str
    state: str
    checked_at: str
    evidence: str
    remediation: str


# Comandos de LEITURA de status, um por fornecedor. Nenhum aqui muta estado:
# nao ha `/login`, `login --device-auth` nem `logout` nesta tabela.
STATUS_COMMANDS: dict[str, str] = {
    "claude": "claude auth status --json",
    "codex": "codex login status",
}

# Fronteira publica de `status()`: aceita "all" alem dos tres fornecedores.
_INDIVIDUAL_PROVIDERS = frozenset({"claude", "codex", "agy"})
_PUBLIC_PROVIDERS = _INDIVIDUAL_PROVIDERS | {"all"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_claude_status(returncode: int, stdout: str) -> AuthResult:
    """Interpreta `claude auth status --json` (A1: contrato estavel, JSON
    limpo em stdout com o campo `loggedIn`).

    A saida negativa explicita (`loggedIn: false`) e suficiente para
    `unauthenticated` sozinha. Ja `authenticated` exige ACORDO entre o
    payload (`loggedIn: true`) e o codigo de saida (0): um `loggedIn: true`
    com codigo != 0 e contraditorio e vira `unknown`, nunca um falso
    positivo. Qualquer coisa que nao seja JSON valido com o campo
    `loggedIn` (JSON invalido, saida vazia por timeout/comando ausente,
    formato inesperado) tambem vira `unknown`.
    """
    checked_at = _now_iso()
    text = stdout if isinstance(stdout, str) else ""
    data = None
    if text.strip():
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            data = None
    logged_in = data.get("loggedIn") if isinstance(data, dict) else None

    if logged_in is False:
        return AuthResult(
            provider="claude",
            state="unauthenticated",
            checked_at=checked_at,
            evidence="claude auth status --json reportou loggedIn=false",
            remediation="asb-agent login",
        )
    if logged_in is True and returncode == 0:
        return AuthResult(
            provider="claude",
            state="authenticated",
            checked_at=checked_at,
            evidence="claude auth status --json reportou loggedIn=true (codigo 0)",
            remediation="",
        )
    return AuthResult(
        provider="claude",
        state="unknown",
        checked_at=checked_at,
        evidence=f"saida nao reconhecida de 'claude auth status --json' (codigo {returncode})",
        remediation="asb-agent auth status --workspace <id> --agent claude --json",
    )


def parse_codex_status(returncode: int, stdout: str, stderr: str) -> AuthResult:
    """Interpreta `codex login status` (A1: 'Not logged in' com codigo 1
    quando deslogado; formato do texto de sucesso nao esta documentado com
    a mesma certeza).

    A negativa explicita ('not logged in') tem PRECEDENCIA sobre qualquer
    substring positiva: 'Not logged in' contem 'logged in', e grepar
    'logged in' sem checar a negativa primeiro casaria os dois estados (o
    mesmo erro historico documentado em LOGIN_CHECKS/lifecycle.py). Sem essa
    negativa, `authenticated` exige codigo 0 E a substring positiva; formato
    desconhecido vira `unknown`, nunca `authenticated` por otimismo.
    """
    checked_at = _now_iso()
    combined = f"{stdout or ''}\n{stderr or ''}".lower()

    if "not logged in" in combined:
        return AuthResult(
            provider="codex",
            state="unauthenticated",
            checked_at=checked_at,
            evidence="codex login status reportou 'Not logged in'",
            remediation="asb-agent login",
        )
    if returncode == 0 and "logged in" in combined:
        return AuthResult(
            provider="codex",
            state="authenticated",
            checked_at=checked_at,
            evidence="codex login status reportou sessao ativa (codigo 0)",
            remediation="",
        )
    return AuthResult(
        provider="codex",
        state="unknown",
        checked_at=checked_at,
        evidence=f"saida nao reconhecida de 'codex login status' (codigo {returncode})",
        remediation="asb-agent auth status --workspace <id> --agent codex --json",
    )


def check_status(provider: str, container: str) -> AuthResult:
    """Verifica o status de UM fornecedor. Nunca inicia login, logout ou
    envia prompt: e leitura pura.

    `provider` aceita apenas claude/codex/agy — 'all' e resolvido por
    `status()`, chamando esta funcao uma vez por fornecedor, e e rejeitado
    aqui.

    Executa como uid 1000 dentro do container do workspace, com o ambiente
    do proprio workspace (nenhuma variavel extra e injetada) e timeout de
    10s via `timeout 10` dentro do container — o mesmo perfil de bounded
    timeout das demais sondas (readiness.py).
    """
    if provider not in _INDIVIDUAL_PROVIDERS:
        raise ValueError(
            f"provider invalido para checagem individual: {provider!r} "
            "(use 'claude', 'codex' ou 'agy'; 'all' so e aceito por status())"
        )

    checked_at = _now_iso()

    if provider == "agy":
        # A1 (empirico): agy nao expoe comando de status local, e
        # `agy -p ping` bloqueia ate 60s aguardando entrada quando deslogado.
        # Sem comando comprovado, respondemos unknown SEM tocar podman —
        # jamais arriscar o bloqueio de 60s numa checagem de diagnostico.
        return AuthResult(
            provider="agy",
            state="unknown",
            checked_at=checked_at,
            evidence=(
                "agy nao possui comando de status local comprovado; "
                "'agy -p ping' bloqueia ate 60s aguardando entrada quando deslogado"
            ),
            remediation="use 'asb-agent auth verify --agent agy' quando disponivel (Tarefa A4)",
        )

    if not podman.running(container):
        # Infraestrutura parada != conta deslogada: nunca reportar
        # unauthenticated quando nem foi possivel perguntar ao fornecedor.
        # ws_hint deriva "demo" de "asb-demo-agent" (mesmo padrao usado em
        # readiness.probe_proxy) para deixar a remediacao copia-e-cola.
        ws_hint = container.removeprefix("asb-").removesuffix("-agent")
        return AuthResult(
            provider=provider,
            state="unreachable",
            checked_at=checked_at,
            evidence=f"container {container} nao esta em execucao",
            remediation=f"asb-agent resume --workspace {ws_hint}",
        )

    command = STATUS_COMMANDS[provider]
    try:
        result = podman.run(
            "exec", "-u", "1000", container,
            "timeout", "10", "bash", "-lc", command,
            check=False, capture=True,
        )
    except podman.PodmanError as exc:
        # Falha ao invocar o proprio podman (binario ausente, exec falhou):
        # erro de infraestrutura, nunca reportado como conta deslogada.
        return AuthResult(
            provider=provider,
            state="provider_error",
            checked_at=checked_at,
            evidence=f"falha ao executar checagem via podman: {exc}",
            remediation="asb-agent doctor",
        )

    stdout = result.stdout or ""
    stderr = getattr(result, "stderr", "") or ""
    returncode = result.returncode

    if provider == "claude":
        parsed = parse_claude_status(returncode, stdout)
    else:
        parsed = parse_codex_status(returncode, stdout, stderr)
    return replace(parsed, checked_at=checked_at)


def _aggregate_exit_code(results: list[AuthResult]) -> int:
    """0 se todos authenticated; 1 se conta ausente/expirada; 2 se algum
    unknown/unreachable/provider_error — com precedencia sobre 1."""
    states = {r.state for r in results}
    if states & {"unknown", "unreachable", "provider_error"}:
        return 2
    if "unauthenticated" in states:
        return 1
    return 0


def status(ws: str, provider: str, *, json_output: bool) -> int:
    """`asb-agent auth status`: relatorio schema 1 de status de conta por
    fornecedor, para um workspace. Nunca inicia login, logout ou envia
    prompt — apenas le.

    Em modo JSON, stdout carrega SOMENTE o relatorio (nada mais e impresso
    ali); diagnosticos vao para stderr em qualquer modo.
    """
    if provider not in _PUBLIC_PROVIDERS:
        raise ValueError(
            f"provedor invalido: {provider!r} (use claude, codex, agy ou all)")

    providers = ("claude", "codex", "agy") if provider == "all" else (provider,)
    container = lifecycle.names(ws)["agent"]
    results = [check_status(p, container) for p in providers]
    checked_at = _now_iso()

    if json_output:
        report = {
            "schemaVersion": 1,
            "workspace": ws,
            "checkedAt": checked_at,
            "results": [
                {
                    "provider": r.provider,
                    "state": r.state,
                    "checkedAt": r.checked_at,
                    "evidence": r.evidence,
                    "remediation": r.remediation,
                }
                for r in results
            ],
        }
        print(json.dumps(report, indent=2))
    else:
        print(f"agent-sandbox auth status ({ws})", file=sys.stderr)
        for r in results:
            marker = "ok   " if r.state == "authenticated" else "FALTA"
            line = f"  {marker} {r.provider}: {r.state} ({r.evidence})"
            if r.remediation:
                line += f"  ->  {r.remediation}"
            print(line, file=sys.stderr)

    return _aggregate_exit_code(results)
