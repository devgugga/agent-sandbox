"""cli/asb/agents/codex.py — driver do Codex CLI.

Fonte do session-id comprovada em
docs/validation/2026-09-17-agent-session-contracts.md (medida no host):
exatamente um novo arquivo `.jsonl` sob `$CODEX_HOME/sessions/**` cuja
primeira linha e um registro
`{"type": "session_meta", "payload": {"id": "...", ...}}`. So a primeira
linha e lida (metadado de sessao, nunca conteudo de transcript).

Dentro do sandbox, `$HOME/.codex/sessions` e o subpath `codex-sessions` do
volume de sessao do workspace; o driver o le PELO HOST, pelo mountpoint do
volume, via `sessions_root`. Sem `sessions_root` nao ha varredura: o
`~/.codex` do operador nunca e lido.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from asb.agents.base import AgentDriver, SessionEvidence
from asb.sessions.model import AgentKind


class CodexDriver(AgentDriver):
    kind = AgentKind.CODEX
    binary = "codex"
    resume_argv_prefix = ("codex", "resume")
    version_pattern = re.compile(r"^codex-cli\s+(\S+)$")
    resume_option_pattern = re.compile(r"(?m)^\s*resume\b")
    session_id_provable = True

    def _scan_root(self, cwd: Path) -> Path | None:
        return self._sessions_root

    def _list_paths(self, root: Path) -> Iterable[Path]:
        return root.rglob("*.jsonl")

    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        candidates = [p for p in evidence.new_paths if p.suffix == ".jsonl"]
        if len(candidates) != 1:
            return None
        try:
            with candidates[0].open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
        except OSError:
            return None
        try:
            record = json.loads(first_line)
        except json.JSONDecodeError:
            return None
        if not isinstance(record, dict):
            return None
        if record.get("type") != "session_meta":
            return None
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return None
        session_id = payload.get("id")
        if isinstance(session_id, str) and session_id:
            return session_id
        return None
