"""cli/asb/agents/antigravity.py — driver do Antigravity CLI (`agy`).

O binario de HOST usado para caracterizar este driver expoe `--conversation`
no seu `--help` (ver
docs/validation/2026-09-17-agent-session-contracts.md), mas isso NAO prova
resume: nenhum diretorio de estado local foi encontrado neste host para
`agy`, entao nao ha fonte de session-id comprovada. `discover_session_id()`
sempre retorna `None` e `probe()` nunca reporta `resume_supported=True`
neste host — o binario da IMAGEM do container e o gate autoritativo para
essa opcao, e so pode ser verificado apos o checkpoint humano (fora do
escopo desta tarefa).
"""
from __future__ import annotations

import re
from pathlib import Path

from asb.agents.base import AgentDriver, SessionEvidence
from asb.sessions.model import AgentKind


class AntigravityDriver(AgentDriver):
    kind = AgentKind.ANTIGRAVITY
    binary = "agy"
    resume_argv_prefix = ("agy", "--conversation")
    version_pattern = re.compile(r"^(\d+(?:\.\d+){1,3})$")
    resume_option_pattern = re.compile(r"--conversation\b")
    # Nao comprovado neste host: nenhum diretorio de estado local foi
    # encontrado para `agy` (~/.agy, ~/.config/agy, ~/.local/share/agy
    # inexistentes). probe() nunca anuncia resume_supported=True aqui,
    # mesmo com a opcao presente no --help.
    session_id_provable = False

    def _scan_root(self, cwd: Path) -> Path | None:
        # Decisao explicita (ver docstring do modulo), nao apenas a
        # heranca silenciosa do padrao da classe base: nenhum diretorio
        # de estado local foi encontrado para `agy` neste host.
        return None

    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        return None
