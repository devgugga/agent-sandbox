"""cli/asb/agents/codex.py — driver do Codex CLI.

Fonte do session-id comprovada em
docs/validation/2026-09-17-agent-session-contracts.md (medida no host):
exatamente um novo arquivo `.jsonl` sob `$CODEX_HOME/sessions/**` cuja
primeira linha e um registro
`{"type": "session_meta", "payload": {"id": "...", ...}}`. So a primeira
linha e lida (metadado de sessao, nunca conteudo de transcript).

O volume de sessao e do WORKSPACE, compartilhado por todos os checkouts
ligados a ele, e e varrido recursivamente: um rollout novo de OUTRA sessao
Codex viva no mesmo workspace pode aparecer durante a descoberta. Por isso
so conta como candidato o arquivo cujo `payload.cwd` (string, caminho
absoluto sem barra final) e o checkout de execucao desta sessao.

O volume tambem e gravavel pelo AGENTE: a leitura abre sem seguir symlink
(`O_NOFOLLOW`), sem bloquear num FIFO (`O_NONBLOCK`), exige arquivo
regular (`fstat`) e le no maximo `_FIRST_LINE_LIMIT` bytes; uma primeira
linha que nao cabe nisso nao da id.

Dentro do sandbox, `$HOME/.codex/sessions` e o subpath `codex-sessions` do
volume de sessao do workspace; o driver o le PELO HOST, pelo mountpoint do
volume, via `sessions_root`. Sem `sessions_root` nao ha varredura: o
`~/.codex` do operador nunca e lido.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Iterable

from asb.agents.base import AgentDriver, SessionEvidence
from asb.sessions.model import AgentKind

# Teto da leitura da primeira linha (o `session_meta` medido tem ~1 KiB).
_FIRST_LINE_LIMIT = 64 * 1024


class CodexDriver(AgentDriver):
    kind = AgentKind.CODEX
    binary = "codex"
    # Como o Orca lanca o Codex: sem aprovacoes nem o sandbox proprio do
    # Codex; o container e a fronteira. `codex resume [OPTIONS]
    # [SESSION_ID]`: a flag vem antes do id (conferido no binario da
    # imagem, 0.153.4).
    permission_args = ("--dangerously-bypass-approvals-and-sandbox",)
    resume_argv_prefix = ("codex", "resume", *permission_args)
    version_pattern = re.compile(r"^codex-cli\s+(\S+)$")
    resume_option_pattern = re.compile(r"(?m)^\s*resume\b")
    session_id_provable = True

    def _scan_root(self, cwd: Path) -> Path | None:
        return self._sessions_root

    def _list_paths(self, root: Path) -> Iterable[Path]:
        return root.rglob("*.jsonl")

    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        if evidence.cwd is None:
            return None
        ids = [session_id for path in evidence.new_paths
               if path.suffix == ".jsonl"
               and (session_id := _session_id_for(path, evidence.cwd))]
        return ids[0] if len(ids) == 1 else None


def _session_id_for(path: Path, cwd: Path) -> str | None:
    """`payload.id` do `session_meta` na primeira linha de `path`, somente
    se `payload.cwd` e o checkout `cwd`; senao `None`."""
    first_line = _read_first_line(path)
    if first_line is None:
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
    session_cwd = payload.get("cwd")
    if not isinstance(session_cwd, str) \
            or PurePosixPath(session_cwd) != PurePosixPath(cwd):
        return None
    session_id = payload.get("id")
    if isinstance(session_id, str) and session_id:
        return session_id
    return None


def _read_first_line(path: Path) -> str | None:
    """Primeira linha de um arquivo REGULAR, sem seguir symlink, sem
    bloquear e lendo no maximo `_FIRST_LINE_LIMIT` bytes; `None` se o
    caminho nao e arquivo regular, nao abre, ou a linha nao termina dentro
    do teto."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data = os.read(fd, _FIRST_LINE_LIMIT)
    except OSError:
        return None
    finally:
        os.close(fd)
    line, newline, _rest = data.partition(b"\n")
    if not newline:
        return None
    return line.decode("utf-8", errors="replace")
