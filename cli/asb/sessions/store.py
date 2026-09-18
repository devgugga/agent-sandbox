"""cli/asb/sessions/store.py — registro atomico de sessoes de agente.

Persiste, sob lock exclusivo `fcntl`, o relacionamento entre uma sessao de
agente (`AgentSession`) e o checkout/terminal/sessao-de-provedor a que ela
esta ligada. Git, Podman, systemd, tmux e as APIs nativas dos provedores
continuam sendo a fonte de verdade sobre o que existe de fato; este registro
guarda apenas o relacionamento observado — nunca prompt, saida de modelo ou
transcricao.

O padrao de escrita atomica (lock `fcntl`, recarga dentro do lock, escrita em
arquivo temporario no mesmo diretorio + `fsync` + `os.replace`) e o mesmo de
`asb.projects.registry`; o plano pede a duplicacao deliberadamente, em vez de
um framework de persistencia compartilhado entre os dois dominios.

Cada sessao guardada carrega sua propria `revision` (comeca em 1 no
`insert()`, incrementa a cada `replace()` bem-sucedido); `replace()` recusa
uma revisao desatualizada com `StaleRevisionError`. O campo `revision` de
nivel superior do arquivo e um contador de mutacoes do arquivo inteiro,
incrementado a cada `insert()`/`replace()`/`remove()` bem-sucedido — os dois
contadores sao independentes.
"""
from __future__ import annotations

import fcntl
import json
import os
import secrets
from dataclasses import replace as _dataclass_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

from asb.checkouts.model import CheckoutId
from asb.sessions.model import (
    AgentKind, AgentSession, ProviderSessionId, SessionId, SessionState,
    TerminalId,
)

_SCHEMA_VERSION = 1
_T = TypeVar("_T")


class SessionStoreError(Exception):
    """Falha ao ler/gravar o registro de sessoes, ou um registro invalido."""


class StaleRevisionError(SessionStoreError):
    """`replace()` chamado com uma `revision` que ja nao e a mais recente."""


class SessionStore:
    """Registro atomico, sem estado em memoria, de sessoes de agente.

    Cada chamada le o arquivo do zero (ou o trata como vazio, se ele ainda
    nao existe) e cada escrita e feita sob um lock `fcntl` exclusivo,
    recarregando dentro do lock antes de gravar — duas instancias apontando
    para o mesmo `path` nunca perdem a escrita uma da outra.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    # -- leitura ------------------------------------------------------------

    def list(self) -> list[AgentSession]:
        _, sessions = self._load()
        return sessions

    def get(self, session_id: SessionId) -> AgentSession:
        _, sessions = self._load()
        for session in sessions:
            if session.id == session_id:
                return session
        raise SessionStoreError(f"unknown session id: {session_id}")

    # -- escrita --------------------------------------------------------------

    def insert(self, session: AgentSession) -> AgentSession:
        session = self._normalize(session)

        def mutate(sessions: list[AgentSession]) -> AgentSession:
            for existing in sessions:
                if existing.id == session.id:
                    raise SessionStoreError(
                        f"duplicate session id: {session.id}")
            stored = _dataclass_replace(session, revision=1)
            sessions.append(stored)
            return stored

        return self._transact(mutate)

    def replace(self, session: AgentSession) -> AgentSession:
        session = self._normalize(session)

        def mutate(sessions: list[AgentSession]) -> AgentSession:
            for index, existing in enumerate(sessions):
                if existing.id == session.id:
                    if existing.revision != session.revision:
                        raise StaleRevisionError(
                            f"stale revision for session {session.id}: "
                            f"expected {existing.revision}, got "
                            f"{session.revision}")
                    updated = _dataclass_replace(
                        session, revision=session.revision + 1)
                    sessions[index] = updated
                    return updated
            raise SessionStoreError(f"unknown session id: {session.id}")

        return self._transact(mutate)

    def _normalize(self, session: AgentSession) -> AgentSession:
        """Valida e normaliza `last_healthy_at` antes de gravar.

        Recusa um datetime naive cedo, sem tocar lock nem arquivo, e trunca
        para precisao de segundos (o que o disco guarda), para que o
        registro devolvido por `insert()`/`replace()` seja igual ao que uma
        leitura subsequente por `get()` devolveria."""
        dt = session.last_healthy_at
        if dt is None:
            return session
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise SessionStoreError(
                f"session {session.id} last_healthy_at must be a "
                "timezone-aware datetime, got a naive one")
        normalized = dt.astimezone(timezone.utc).replace(microsecond=0)
        return _dataclass_replace(session, last_healthy_at=normalized)

    def remove(self, session_id: SessionId) -> None:
        def mutate(sessions: list[AgentSession]) -> None:
            for index, existing in enumerate(sessions):
                if existing.id == session_id:
                    del sessions[index]
                    return
            raise SessionStoreError(f"unknown session id: {session_id}")

        self._transact(mutate)

    # -- lock + leitura/gravacao atomica --------------------------------------

    def _transact(
        self, mutate: Callable[[list[AgentSession]], _T],
    ) -> _T:
        """Executa `mutate` sob lock exclusivo, recarregando antes de gravar.

        `mutate` recebe a lista de sessoes recem-lida do disco, pode
        modifica-la in place, e devolve o resultado a repassar para o
        chamador. O arquivo so e reescrito se `mutate` nao levantar — um
        arquivo corrompido, de schema desconhecido, ou uma revisao
        desatualizada nunca chegam a ser sobrescritos.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)

        lock_path = self.path.with_name(self.path.name + ".lock")
        lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                file_revision, sessions = self._load()
                result = mutate(sessions)
                self._write(file_revision + 1, sessions)
                return result
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

    def _load(self) -> tuple[int, list[AgentSession]]:
        if not self.path.exists():
            return 0, []
        return self._decode(self.path.read_text(encoding="utf-8"))

    def _decode(self, text: str) -> tuple[int, list[AgentSession]]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SessionStoreError(
                f"corrupt session store JSON at {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise SessionStoreError(
                f"session store root must be a JSON object: {self.path}")
        if data.get("schemaVersion") != _SCHEMA_VERSION:
            raise SessionStoreError(
                "unsupported session store schema version "
                f"{data.get('schemaVersion')!r} at {self.path}")
        file_revision = data.get("revision")
        if isinstance(file_revision, bool) or not isinstance(file_revision, int):
            raise SessionStoreError(
                f"session store missing or invalid top-level 'revision' at "
                f"{self.path}: {file_revision!r}")

        sessions: list[AgentSession] = []
        for raw in data.get("sessions", []):
            if not isinstance(raw, dict):
                raise SessionStoreError(
                    f"session entry must be a JSON object at {self.path}: "
                    f"{raw!r}")
            sessions.append(self._decode_session(raw))
        return file_revision, sessions

    def _decode_session(self, raw: dict) -> AgentSession:
        session_id = self._decode_id(raw, "id", SessionId)
        checkout_id = self._decode_id(raw, "checkoutId", CheckoutId)
        agent = self._decode_enum(raw, "agent", AgentKind)
        title = self._required_str(raw, "title")
        cwd = Path(self._required_str(raw, "cwd"))
        terminal_id = self._decode_optional_id(raw, "terminalId", TerminalId)
        provider_session_id = self._decode_optional_id(
            raw, "providerSessionId", ProviderSessionId)
        state = self._decode_enum(raw, "state", SessionState)
        last_healthy_at = self._decode_last_healthy_at(raw)
        revision = self._decode_revision(raw)
        return AgentSession(
            id=session_id,
            checkout_id=checkout_id,
            agent=agent,
            cwd=cwd,
            title=title,
            state=state,
            terminal_id=terminal_id,
            provider_session_id=provider_session_id,
            last_healthy_at=last_healthy_at,
            revision=revision,
        )

    def _required_str(self, raw: dict, key: str) -> str:
        """Retorna `raw[key]`, ou levanta `SessionStoreError` nomeando o
        campo quando ele esta ausente ou nao e uma string — nunca deixa um
        `KeyError`/`TypeError` bruto escapar para o chamador."""
        value = raw.get(key)
        if not isinstance(value, str):
            raise SessionStoreError(
                f"session entry missing or invalid required field {key!r} "
                f"at {self.path}: {value!r}")
        return value

    def _decode_id(self, raw: dict, key: str, id_type: type) -> object:
        value = self._required_str(raw, key)
        try:
            return id_type(value)
        except ValueError as exc:
            raise SessionStoreError(
                f"session entry has invalid {key!r} at {self.path}: "
                f"{value!r}") from exc

    def _decode_optional_id(self, raw: dict, key: str, id_type: type) -> object | None:
        if key not in raw:
            raise SessionStoreError(
                f"session entry missing required field {key!r} at "
                f"{self.path}")
        value = raw[key]
        if value is None:
            return None
        if not isinstance(value, str):
            raise SessionStoreError(
                f"session entry has invalid {key!r} at {self.path}: "
                f"{value!r}")
        try:
            return id_type(value)
        except ValueError as exc:
            raise SessionStoreError(
                f"session entry has invalid {key!r} at {self.path}: "
                f"{value!r}") from exc

    def _decode_enum(self, raw: dict, key: str, enum_type: type) -> object:
        value = self._required_str(raw, key)
        try:
            return enum_type(value)
        except ValueError as exc:
            raise SessionStoreError(
                f"session entry has invalid {key!r} at {self.path}: "
                f"{value!r}") from exc

    def _decode_last_healthy_at(self, raw: dict) -> datetime | None:
        if "lastHealthyAt" not in raw:
            raise SessionStoreError(
                f"session entry missing required field 'lastHealthyAt' at "
                f"{self.path}")
        value = raw["lastHealthyAt"]
        if value is None:
            return None
        if not isinstance(value, str) or not value.endswith("Z"):
            raise SessionStoreError(
                "session entry field 'lastHealthyAt' must be an ISO-8601 "
                f"UTC timestamp ending in 'Z' at {self.path}: {value!r}")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise SessionStoreError(
                "session entry field 'lastHealthyAt' is not a valid "
                f"ISO-8601 timestamp at {self.path}: {value!r}") from exc
        return parsed.astimezone(timezone.utc)

    def _decode_revision(self, raw: dict) -> int:
        value = raw.get("revision")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise SessionStoreError(
                f"session entry missing or invalid 'revision' at "
                f"{self.path}: {value!r}")
        return value

    def _write(self, file_revision: int, sessions: list[AgentSession]) -> None:
        payload = {
            "schemaVersion": _SCHEMA_VERSION,
            "revision": file_revision,
            "sessions": [self._encode_session(session) for session in sessions],
        }
        text = json.dumps(payload, indent=2) + "\n"

        tmp_path = self.path.with_name(
            f"{self.path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
        tmp_fd = os.open(str(tmp_path),
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(tmp_path), str(self.path))
        except BaseException:
            try:
                os.remove(tmp_path)
            except FileNotFoundError:
                pass
            raise
        os.chmod(self.path, 0o600)

    def _encode_session(self, session: AgentSession) -> dict:
        return {
            "id": str(session.id),
            "checkoutId": str(session.checkout_id),
            "agent": str(session.agent),
            "title": session.title,
            "cwd": str(session.cwd),
            "terminalId": (str(session.terminal_id)
                          if session.terminal_id is not None else None),
            "providerSessionId": (str(session.provider_session_id)
                                  if session.provider_session_id is not None
                                  else None),
            "state": str(session.state),
            "lastHealthyAt": self._encode_last_healthy_at(session),
            "revision": session.revision,
        }

    def _encode_last_healthy_at(self, session: AgentSession) -> str | None:
        dt = session.last_healthy_at
        if dt is None:
            return None
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise SessionStoreError(
                f"session {session.id} last_healthy_at must be a "
                "timezone-aware datetime, got a naive one")
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
