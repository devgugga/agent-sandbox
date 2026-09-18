"""cli/asb/agents/claude.py — driver do Claude Code CLI.

Fonte do session-id comprovada em
docs/validation/2026-09-17-agent-session-contracts.md (medida no host):
exatamente um novo arquivo `<uuid>.jsonl` sob
`~/.claude/projects/<slug(cwd)>/`, onde `slug()` substitui `/` e `.` por
`-`. O UUID vem do NOME do arquivo — nenhum conteudo de transcript e lido.

Dentro do sandbox, `$HOME/.claude/projects` e o subpath `claude-projects`
do volume de sessao do workspace; o driver o le PELO HOST, pelo mountpoint
do volume, via `sessions_root`. `cwd` e o checkout de execucao do sandbox
(`ConnectionInfo.project_root`, mesmo caminho absoluto no host e no
container). Sem `sessions_root` nao ha varredura: o `~/.claude` do operador
nunca e lido.
"""
from __future__ import annotations

import re
from pathlib import Path

from asb.agents.base import AgentDriver, SessionEvidence
from asb.sessions.model import AgentKind

_SLUG_CHARS = re.compile(r"[/.]")


def _slugify(cwd: Path) -> str:
    return _SLUG_CHARS.sub("-", str(cwd.resolve()))


class ClaudeDriver(AgentDriver):
    kind = AgentKind.CLAUDE
    binary = "claude"
    resume_argv_prefix = ("claude", "--resume")
    version_pattern = re.compile(r"^(\S+)\s+\(Claude Code\)$")
    resume_option_pattern = re.compile(r"--resume\b")
    session_id_provable = True

    def _scan_root(self, cwd: Path) -> Path | None:
        if self._sessions_root is None:
            return None
        return self._sessions_root / _slugify(cwd)

    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        candidates = [p for p in evidence.new_paths if p.suffix == ".jsonl"]
        if len(candidates) != 1:
            return None
        return candidates[0].stem
