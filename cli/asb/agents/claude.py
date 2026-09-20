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
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from asb.agents.base import AgentDriver, LaunchCommand, SessionEvidence
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

    def launch(self, cwd: Path,
               session_id: str | None = None) -> LaunchCommand:
        validated = _canonical_uuid(session_id)
        return LaunchCommand(argv=(self.binary, "--session-id", validated,
                                   *self.permission_args))

    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        """Nunca descobre: o id e atribuido no lancamento."""
        return None
