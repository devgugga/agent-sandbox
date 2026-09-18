"""cli/asb/agents/claude.py — driver do Claude Code CLI.

Fonte do session-id comprovada em
docs/validation/2026-09-17-agent-session-contracts.md: exatamente um novo
arquivo `<uuid>.jsonl` sob `~/.claude/projects/<slug(cwd)>/`, onde `slug()`
substitui `/` e `.` por `-`. O UUID vem do NOME do arquivo — nenhum
conteudo de transcript e lido.
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
        home = self._state_home if self._state_home is not None \
            else Path.home() / ".claude"
        return home / "projects" / _slugify(cwd)

    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        candidates = [p for p in evidence.new_paths if p.suffix == ".jsonl"]
        if len(candidates) != 1:
            return None
        return candidates[0].stem
