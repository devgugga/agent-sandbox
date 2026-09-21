"""cli/asb/agents/claude.py — driver do Claude Code CLI.

O id da sessao e ATRIBUIDO no lancamento, nao descoberto: o manager gera um
UUID, o grava como `provider_session_id` antes de lancar e o driver lanca
`claude --session-id <uuid>`; o resume e `claude --resume <uuid>`. O binario
da imagem lista `--session-id <uuid>` ("must be a valid UUID"); a versao e a
que o binario instalado pelo mise reporta, registrada em
`/opt/asb-mise/versions` na imagem (nao ha pin no Dockerfile: o build
instala `latest`).
Por isso o driver nao varre diretorio nenhum: a descoberta por arquivo novo
em `~/.claude/projects/<slug>/` falhou no piloto, porque o Claude so cria o
arquivo na primeira mensagem, depois da janela de descoberta.

Claude lanca e retoma com `--dangerously-skip-permissions`, como o Orca o
lanca: o sandbox e a fronteira de isolamento.

Regras de autenticacao (Tarefa 2 da decomposicao de `auth.py`): `claude
auth status --json` e o unico comando de status comprovado (A1); a saida
negativa explicita (`loggedIn: false`) basta sozinha para
`unauthenticated`, e `authenticated` exige ACORDO entre o payload
(`loggedIn: true`) e o codigo de saida (0). O login real e `claude auth
login` — `claude /login` responde "isn't available in this environment" e
sai com codigo 0 SEM logar (A1, Claude Code 2.1.263). A verificacao real
usa `claude -p <prompt>`, nunca `--console` (que selecionaria faturamento
por API em vez da assinatura) nem `--version` (responde 0 deslogado).
"""
from __future__ import annotations

import json
import re
import shlex
import uuid
from pathlib import Path

from asb.agents.base import (AgentDriver, AuthResult, LaunchCommand,
                             SessionEvidence, _now_iso, _verify_setup_script,
                             _VERIFY_PROMPT, _VERIFY_PROVIDER_TIMEOUT)
from asb.sessions.model import AgentKind, ProviderSessionId

_SKIP_PERMISSIONS = "--dangerously-skip-permissions"


def _canonical_uuid(value: object) -> ProviderSessionId:
    """`value` so passa se ja e um UUID na forma canonica (minusculas, com
    hifens), que o `--session-id` do Claude aceita e o `ProviderSessionId`
    tambem."""
    if not isinstance(value, str):
        raise ValueError(f"claude session id must be a UUID: {value!r}")
    try:
        canonical = str(uuid.UUID(value))
    except ValueError as exc:
        raise ValueError(
            f"claude session id must be a UUID: {value!r}") from exc
    if canonical != value:
        raise ValueError(
            f"claude session id must be a canonical UUID: {value!r}")
    return ProviderSessionId(value)


class ClaudeDriver(AgentDriver):
    kind = AgentKind.CLAUDE
    binary = "claude"
    permission_args = (_SKIP_PERMISSIONS,)
    # `--resume [value]` tem valor opcional: o id vem logo depois dele.
    resume_argv_prefix = ("claude", "--resume")
    resume_argv_suffix = (_SKIP_PERMISSIONS,)
    version_pattern = re.compile(r"^(\S+)\s+\(Claude Code\)$")
    resume_option_pattern = re.compile(r"--resume\b")
    session_id_provable = True
    assigns_session_id_at_launch = True

    # -- autenticacao (Tarefa 2) -------------------------------------------

    provider = "claude"
    status_command = "claude auth status --json"
    auth_evidence_markers = (
        "invalid x-api-key", "authentication_error", "not logged in",
        "please run /login", "invalid bearer token",
    )

    def launch(self, cwd: Path,
               session_id: str | None = None) -> LaunchCommand:
        validated = _canonical_uuid(session_id)
        return LaunchCommand(argv=(self.binary, "--session-id", validated,
                                   *self.permission_args))

    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        """Nunca descobre: o id e atribuido no lancamento."""
        return None

    def parse_auth_status(self, completed) -> AuthResult:
        """Interpreta `claude auth status --json` (A1: contrato estavel,
        JSON limpo em stdout com o campo `loggedIn`).

        A saida negativa explicita (`loggedIn: false`) e suficiente para
        `unauthenticated` sozinha. Ja `authenticated` exige ACORDO entre o
        payload (`loggedIn: true`) e o codigo de saida (0): um
        `loggedIn: true` com codigo != 0 e contraditorio e vira `unknown`,
        nunca um falso positivo. Qualquer coisa que nao seja JSON valido
        com o campo `loggedIn` (JSON invalido, saida vazia por
        timeout/comando ausente, formato inesperado) tambem vira
        `unknown`.
        """
        checked_at = _now_iso()
        returncode = completed.returncode
        text = completed.stdout if isinstance(completed.stdout, str) else ""
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

    def login_argv(self) -> tuple[str, ...]:
        return ("claude", "auth", "login")

    def verify_argv(self) -> tuple[str, ...]:
        """Script remoto de UMA chamada real: `claude -p <prompt>`, flag
        confirmada offline na versao fixada (`claude --help`), sem tocar
        rede."""
        prompt = shlex.quote(_VERIFY_PROMPT)
        setup = _verify_setup_script()
        return (f"{setup}timeout {_VERIFY_PROVIDER_TIMEOUT} "
                f"asb-claude -p {prompt} < /dev/null",)
