"""Testes do registro atomico de sessoes (`asb.sessions.store`).

Cobre round-trip de todo estado de sessao, arquivo ausente como estado
vazio, rejeicao de id duplicado, rejeicao de revisao desatualizada em
`replace()`, rejeicao de schema desconhecido, preservacao do arquivo diante
de JSON corrompido ou de campo invalido, ausencia de campos de
prompt/saida, permissoes de arquivo/diretorio, e escritas concorrentes de
duas instancias sem perda.

Nenhum teste toca Podman, systemd, tmux ou credenciais; tudo roda em
diretorios temporarios.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import json
import secrets
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.checkouts.model import CheckoutId  # noqa: E402
from asb.sessions.model import (  # noqa: E402
    AgentKind, AgentSession, ProviderSessionId, SessionId, SessionState,
    TerminalId,
)
from asb.sessions.store import (  # noqa: E402
    SessionStore, SessionStoreError, StaleRevisionError,
)


def _new_id() -> str:
    return secrets.token_hex(8)


def _make_session(
    *,
    session_id: SessionId | None = None,
    checkout_id: CheckoutId | None = None,
    agent: AgentKind = AgentKind.CODEX,
    title: str = "Plan work",
    cwd: Path = Path("/sandbox/repo"),
    state: SessionState = SessionState.STARTING,
    terminal_id: TerminalId | None = None,
    provider_session_id: ProviderSessionId | None = None,
    last_healthy_at: datetime | None = None,
    revision: int = 0,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> AgentSession:
    return AgentSession(
        id=session_id or SessionId(f"s-{_new_id()}"),
        checkout_id=checkout_id or CheckoutId(f"c-{_new_id()}"),
        agent=agent,
        cwd=cwd,
        title=title,
        state=state,
        terminal_id=terminal_id,
        provider_session_id=provider_session_id,
        last_healthy_at=last_healthy_at,
        revision=revision,
        started_at=started_at,
        ended_at=ended_at,
    )


def _valid_raw_session(**overrides: object) -> dict:
    raw = {
        "id": "s-0123456789abcdef",
        "checkoutId": "c-0123456789abcdef",
        "agent": "codex",
        "title": "Plan work",
        "cwd": "/sandbox/repo",
        "terminalId": "asb-s-0123456789abcdef",
        "providerSessionId": None,
        "state": "detached",
        "lastHealthyAt": "2026-09-17T20:00:00Z",
        "revision": 1,
    }
    raw.update(overrides)
    return raw


class SessionStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.tmp = Path(self._tempdir.name)
        self.store_path = self.tmp / "state" / "sessions.json"

    def store(self) -> SessionStore:
        return SessionStore(self.store_path)

    def _seed(self, payload: dict) -> str:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload)
        self.store_path.write_text(text, encoding="utf-8")
        return text

    def _seed_sessions(self, *sessions: dict) -> str:
        return self._seed({
            "schemaVersion": 1,
            "revision": 1,
            "sessions": list(sessions),
        })


class EmptyAndRoundTripTests(SessionStoreTestCase):
    def test_missing_file_reads_as_empty(self):
        store = self.store()
        self.assertEqual(store.list(), [])

    def test_insert_and_get_round_trip(self):
        store = self.store()
        session = _make_session()
        stored = store.insert(session)
        self.assertEqual(stored.revision, 1)
        fetched = store.get(session.id)
        self.assertEqual(fetched, stored)

    def test_round_trips_every_session_state(self):
        store = self.store()
        for state in SessionState:
            session = _make_session(state=state)
            store.insert(session)
            fetched = store.get(session.id)
            self.assertEqual(fetched.state, state)


class InsertRejectionTests(SessionStoreTestCase):
    def test_insert_duplicate_id_raises_and_leaves_file_unchanged(self):
        store = self.store()
        session = _make_session()
        store.insert(session)
        before = self.store_path.read_text()

        duplicate = _make_session(session_id=session.id)
        with self.assertRaises(SessionStoreError):
            store.insert(duplicate)
        self.assertEqual(self.store_path.read_text(), before)


class GetAndRemoveTests(SessionStoreTestCase):
    def test_get_unknown_id_raises(self):
        store = self.store()
        with self.assertRaises(SessionStoreError):
            store.get(SessionId("s-0000000000000000"))

    def test_remove_unknown_id_raises(self):
        store = self.store()
        with self.assertRaises(SessionStoreError):
            store.remove(SessionId("s-0000000000000000"))

    def test_remove_deletes_session(self):
        store = self.store()
        session = _make_session()
        store.insert(session)
        store.remove(session.id)
        self.assertEqual(store.list(), [])
        with self.assertRaises(SessionStoreError):
            store.get(session.id)


class ReplaceAndRevisionTests(SessionStoreTestCase):
    def test_replace_updates_fields_and_increments_revision(self):
        store = self.store()
        record = store.insert(_make_session(state=SessionState.STARTING))
        updated = record.with_state(SessionState.RUNNING)
        result = store.replace(updated)

        self.assertEqual(result.revision, 2)
        self.assertEqual(result.state, SessionState.RUNNING)
        fetched = store.get(record.id)
        self.assertEqual(fetched, result)

    def test_replace_unknown_id_raises(self):
        store = self.store()
        session = _make_session(revision=1)
        with self.assertRaises(SessionStoreError):
            store.replace(session)

    def test_replace_stale_revision_rejected_and_leaves_file_unchanged(self):
        store_a = self.store()
        store_b = self.store()

        record = store_a.insert(_make_session())
        seen_by_a = store_a.get(record.id)
        seen_by_b = store_b.get(record.id)
        self.assertEqual(seen_by_a, seen_by_b)

        store_a.replace(seen_by_a.with_state(SessionState.RUNNING))
        after_a = self.store_path.read_text()

        with self.assertRaises(StaleRevisionError):
            store_b.replace(seen_by_b.with_state(SessionState.FAILED))

        self.assertEqual(self.store_path.read_text(), after_a)


class ConcurrencyTests(SessionStoreTestCase):
    def test_two_instances_interleaving_inserts_lose_no_write(self):
        worker_count = 20
        barrier = threading.Barrier(worker_count)
        errors: list[BaseException] = []
        sessions = [_make_session() for _ in range(worker_count)]

        def worker(index: int) -> None:
            try:
                barrier.wait(timeout=5)
                SessionStore(self.store_path).insert(sessions[index])
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,))
                  for i in range(worker_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        stored_ids = {s.id for s in self.store().list()}
        self.assertEqual(stored_ids, {s.id for s in sessions})


class PersistenceShapeTests(SessionStoreTestCase):
    def test_stored_session_has_exact_key_set(self):
        store = self.store()
        store.insert(_make_session())
        on_disk = json.loads(self.store_path.read_text())
        entry = on_disk["sessions"][0]
        self.assertEqual(set(entry.keys()), {
            "id", "checkoutId", "agent", "title", "cwd", "terminalId",
            "providerSessionId", "state", "lastHealthyAt", "revision",
            "startedAt", "endedAt",
        })

    def test_json_schema_version_and_top_level_revision(self):
        store = self.store()
        store.insert(_make_session())
        store.insert(_make_session())
        on_disk = json.loads(self.store_path.read_text())
        self.assertEqual(on_disk["schemaVersion"], 1)
        self.assertEqual(on_disk["revision"], 2)
        self.assertEqual(len(on_disk["sessions"]), 2)

    def test_file_and_directory_modes(self):
        store = self.store()
        store.insert(_make_session())
        self.assertEqual(self.store_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store_path.parent.stat().st_mode & 0o777, 0o700)

    def test_lock_file_has_mode_0600(self):
        store = self.store()
        store.insert(_make_session())
        lock_path = self.store_path.with_name(self.store_path.name + ".lock")
        self.assertTrue(lock_path.exists())
        self.assertEqual(lock_path.stat().st_mode & 0o777, 0o600)

    def test_no_prompt_or_output_fields(self):
        store = self.store()
        store.insert(_make_session())
        on_disk = json.loads(self.store_path.read_text())
        entry = on_disk["sessions"][0]
        self.assertNotIn("prompt", entry)
        self.assertNotIn("output", entry)
        self.assertNotIn("transcript", entry)

    def test_terminal_and_provider_session_id_survive_round_trip_as_strings(self):
        store = self.store()
        session = _make_session(
            terminal_id=TerminalId("asb-s-0123456789abcdef"),
            provider_session_id=ProviderSessionId("raw-provider-id"))
        store.insert(session)

        on_disk = json.loads(self.store_path.read_text())
        entry = on_disk["sessions"][0]
        self.assertEqual(entry["terminalId"], "asb-s-0123456789abcdef")
        self.assertEqual(entry["providerSessionId"], "raw-provider-id")

        fetched = store.get(session.id)
        self.assertEqual(fetched.terminal_id, "asb-s-0123456789abcdef")
        self.assertEqual(fetched.provider_session_id, "raw-provider-id")


class WireFormatConformanceTests(SessionStoreTestCase):
    """The brief's own example, decoded uncorrupted: pins the baseline that
    every `DecoderRejectionTests` case corrupts a single field of."""

    def test_decodes_the_briefs_example_session_verbatim(self):
        self._seed_sessions(_valid_raw_session())
        store = self.store()

        sessions = store.list()
        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertEqual(session.id, "s-0123456789abcdef")
        self.assertEqual(session.checkout_id, "c-0123456789abcdef")
        self.assertEqual(session.agent, AgentKind.CODEX)
        self.assertEqual(session.title, "Plan work")
        self.assertEqual(session.cwd, Path("/sandbox/repo"))
        self.assertEqual(session.terminal_id, "asb-s-0123456789abcdef")
        self.assertIsNone(session.provider_session_id)
        self.assertEqual(session.state, SessionState.DETACHED)
        self.assertEqual(
            session.last_healthy_at,
            datetime(2026, 9, 17, 20, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(session.revision, 1)


class LastHealthyAtTests(SessionStoreTestCase):
    def test_round_trips_last_healthy_at_as_iso8601_utc_with_z(self):
        store = self.store()
        moment = datetime(2026, 9, 17, 20, 0, 0, tzinfo=timezone.utc)
        session = _make_session(last_healthy_at=moment)
        store.insert(session)

        on_disk = json.loads(self.store_path.read_text())
        self.assertEqual(
            on_disk["sessions"][0]["lastHealthyAt"], "2026-09-17T20:00:00Z")

        fetched = store.get(session.id)
        self.assertEqual(fetched.last_healthy_at, moment)

    def test_null_last_healthy_at_round_trips_as_null(self):
        store = self.store()
        session = _make_session(last_healthy_at=None)
        store.insert(session)
        fetched = store.get(session.id)
        self.assertIsNone(fetched.last_healthy_at)

    def test_insert_rejects_naive_last_healthy_at_and_leaves_no_file(self):
        store = self.store()
        naive = datetime(2026, 9, 17, 20, 0, 0)  # no tzinfo
        session = _make_session(last_healthy_at=naive)
        with self.assertRaises(SessionStoreError):
            store.insert(session)
        self.assertFalse(self.store_path.exists())

    def test_malformed_timestamp_raises_and_leaves_file_unchanged(self):
        # No trailing "Z": rejected by the endswith() guard, fromisoformat()
        # never called.
        raw = _valid_raw_session(lastHealthyAt="2026-09-17 20:00:00")
        before = self._seed_sessions(raw)
        store = self.store()

        with self.assertRaises(SessionStoreError):
            store.list()
        with self.assertRaises(SessionStoreError):
            store.insert(_make_session())
        self.assertEqual(self.store_path.read_text(), before)

    def test_timestamp_ending_in_z_but_unparseable_raises_and_leaves_file_unchanged(self):
        # Passes the endswith("Z") guard, then fails inside fromisoformat().
        raw = _valid_raw_session(lastHealthyAt="not-a-real-timestampZ")
        before = self._seed_sessions(raw)
        store = self.store()

        with self.assertRaises(SessionStoreError):
            store.list()
        with self.assertRaises(SessionStoreError):
            store.insert(_make_session())
        self.assertEqual(self.store_path.read_text(), before)

    def test_missing_last_healthy_at_key_raises_and_leaves_file_unchanged(self):
        raw = _valid_raw_session()
        del raw["lastHealthyAt"]
        before = self._seed_sessions(raw)
        store = self.store()

        with self.assertRaises(SessionStoreError):
            store.list()
        with self.assertRaises(SessionStoreError):
            store.insert(_make_session())
        self.assertEqual(self.store_path.read_text(), before)


class StartedAtTests(SessionStoreTestCase):
    """`startedAt` e opcional: registros gravados antes dele (sem a chave)
    decodificam como `None`; um valor presente segue a regra estrita de
    `lastHealthyAt` (UTC com `Z`, datetime aware, truncado ao segundo)."""

    def test_round_trips_started_at_truncated_to_seconds(self):
        store = self.store()
        moment = datetime(2026, 9, 19, 14, 36, 14, 987654,
                          tzinfo=timezone.utc)
        inserted = store.insert(_make_session(started_at=moment))
        self.assertEqual(inserted.started_at, moment.replace(microsecond=0))
        on_disk = json.loads(self.store_path.read_text())
        self.assertEqual(on_disk["sessions"][0]["startedAt"],
                         "2026-09-19T14:36:14Z")
        self.assertEqual(store.get(inserted.id), inserted)

    def test_none_is_written_as_null_and_read_back_as_none(self):
        store = self.store()
        inserted = store.insert(_make_session())
        on_disk = json.loads(self.store_path.read_text())
        self.assertIsNone(on_disk["sessions"][0]["startedAt"])
        self.assertIsNone(store.get(inserted.id).started_at)

    def test_a_record_without_the_key_decodes_as_none(self):
        raw = _valid_raw_session()
        self.assertNotIn("startedAt", raw)
        self._seed_sessions(raw)
        [session] = self.store().list()
        self.assertIsNone(session.started_at)

    def test_a_record_without_the_key_can_still_be_replaced(self):
        self._seed_sessions(_valid_raw_session())
        store = self.store()
        [session] = store.list()
        updated = store.replace(session.with_state(SessionState.DETACHED))
        self.assertIsNone(updated.started_at)
        self.assertEqual(store.get(session.id), updated)

    def test_insert_rejects_naive_started_at_and_leaves_no_file(self):
        with self.assertRaises(SessionStoreError):
            self.store().insert(_make_session(
                started_at=datetime(2026, 9, 19, 14, 36, 14)))
        self.assertFalse(self.store_path.exists())

    def test_invalid_started_at_raises_and_leaves_file_unchanged(self):
        for value in ("2026-09-19 14:36:14", "not-a-real-timestampZ", 7,
                      True, ["2026-09-19T14:36:14Z"]):
            with self.subTest(value=value):
                before = self._seed_sessions(
                    _valid_raw_session(startedAt=value))
                store = self.store()
                with self.assertRaises(SessionStoreError):
                    store.list()
                with self.assertRaises(SessionStoreError):
                    store.insert(_make_session())
                self.assertEqual(self.store_path.read_text(), before)


class EndedAtTests(SessionStoreTestCase):
    """`endedAt` e carimbado pelo relogio do store, arredondado PARA CIMA
    ao segundo, na primeira escrita de um estado final; opcional na
    leitura como `startedAt`."""

    CLOCK = datetime(2026, 9, 19, 15, 0, 0, 250000, tzinfo=timezone.utc)
    STAMP = datetime(2026, 9, 19, 15, 0, 1, tzinfo=timezone.utc)

    def clocked(self) -> SessionStore:
        return SessionStore(self.store_path, clock=lambda: self.CLOCK)

    def test_a_final_write_stamps_ended_at_rounded_up(self):
        for state in (SessionState.COMPLETED, SessionState.FAILED):
            with self.subTest(state=state):
                store = self.clocked()
                live = store.insert(_make_session())
                done = store.replace(live.with_state(state))
                self.assertEqual(done.ended_at, self.STAMP)
                on_disk = json.loads(self.store_path.read_text())
                entry = next(e for e in on_disk["sessions"]
                             if e["id"] == done.id)
                self.assertEqual(entry["endedAt"], "2026-09-19T15:00:01Z")
                self.assertEqual(store.get(done.id), done)

    def test_a_whole_second_clock_is_not_rounded(self):
        whole = datetime(2026, 9, 19, 15, 0, 0, tzinfo=timezone.utc)
        store = SessionStore(self.store_path, clock=lambda: whole)
        done = store.insert(_make_session(state=SessionState.COMPLETED))
        self.assertEqual(done.ended_at, whole)

    def test_an_existing_ended_at_is_kept(self):
        store = self.clocked()
        earlier = datetime(2026, 9, 19, 14, 0, tzinfo=timezone.utc)
        done = store.insert(_make_session(state=SessionState.COMPLETED,
                                          ended_at=earlier))
        self.assertEqual(done.ended_at, earlier)
        again = store.replace(done.with_state(SessionState.COMPLETED))
        self.assertEqual(again.ended_at, earlier)

    def test_a_non_final_write_leaves_it_none(self):
        store = self.clocked()
        for state in SessionState:
            if state in (SessionState.COMPLETED, SessionState.FAILED):
                continue
            with self.subTest(state=state):
                self.assertIsNone(store.insert(
                    _make_session(state=state)).ended_at)

    def test_a_record_without_the_key_decodes_as_none(self):
        self._seed_sessions(_valid_raw_session(state="completed"))
        [session] = self.store().list()
        self.assertIsNone(session.ended_at)

    def test_invalid_ended_at_raises_and_leaves_file_unchanged(self):
        for value in ("2026-09-19 15:00:00", 7, "garbageZ"):
            with self.subTest(value=value):
                before = self._seed_sessions(
                    _valid_raw_session(endedAt=value))
                with self.assertRaises(SessionStoreError):
                    self.store().list()
                self.assertEqual(self.store_path.read_text(), before)


class DecoderRejectionTests(SessionStoreTestCase):
    def _assert_raw_session_rejected_untouched(self, raw: dict) -> None:
        before = self._seed_sessions(raw)
        store = self.store()

        with self.assertRaises(SessionStoreError):
            store.list()
        with self.assertRaises(SessionStoreError):
            store.insert(_make_session())
        self.assertEqual(self.store_path.read_text(), before)

    def test_bad_state_raises_and_leaves_file_unchanged(self):
        self._assert_raw_session_rejected_untouched(
            _valid_raw_session(state="not-a-state"))

    def test_bad_agent_raises_and_leaves_file_unchanged(self):
        self._assert_raw_session_rejected_untouched(
            _valid_raw_session(agent="not-an-agent"))

    def test_bad_id_raises_and_leaves_file_unchanged(self):
        self._assert_raw_session_rejected_untouched(
            _valid_raw_session(id="not a valid id!"))

    def test_missing_key_raises_and_leaves_file_unchanged(self):
        raw = _valid_raw_session()
        del raw["cwd"]
        self._assert_raw_session_rejected_untouched(raw)

    def test_revision_as_bool_raises_and_leaves_file_unchanged(self):
        self._assert_raw_session_rejected_untouched(
            _valid_raw_session(revision=True))

    def test_revision_as_zero_raises_and_leaves_file_unchanged(self):
        self._assert_raw_session_rejected_untouched(
            _valid_raw_session(revision=0))

    def test_missing_terminal_id_key_raises_and_leaves_file_unchanged(self):
        raw = _valid_raw_session()
        del raw["terminalId"]
        self._assert_raw_session_rejected_untouched(raw)

    def test_terminal_id_wrong_type_raises_and_leaves_file_unchanged(self):
        self._assert_raw_session_rejected_untouched(
            _valid_raw_session(terminalId=12345))

    def test_terminal_id_invalid_value_raises_and_leaves_file_unchanged(self):
        self._assert_raw_session_rejected_untouched(
            _valid_raw_session(terminalId="BAD ID"))

    def test_top_level_revision_missing_raises_and_leaves_file_unchanged(self):
        before = self._seed({"schemaVersion": 1, "sessions": []})
        store = self.store()
        with self.assertRaises(SessionStoreError):
            store.list()
        with self.assertRaises(SessionStoreError):
            store.insert(_make_session())
        self.assertEqual(self.store_path.read_text(), before)

    def test_top_level_revision_as_bool_raises_and_leaves_file_unchanged(self):
        before = self._seed({"schemaVersion": 1, "revision": True, "sessions": []})
        store = self.store()
        with self.assertRaises(SessionStoreError):
            store.list()
        with self.assertRaises(SessionStoreError):
            store.insert(_make_session())
        self.assertEqual(self.store_path.read_text(), before)

    def test_corrupt_json_raises_and_leaves_file_untouched(self):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text("{not json", encoding="utf-8")
        store = self.store()
        with self.assertRaises(SessionStoreError):
            store.list()
        with self.assertRaises(SessionStoreError):
            store.insert(_make_session())
        self.assertEqual(self.store_path.read_text(), "{not json")

    def test_non_object_root_raises_and_leaves_file_untouched(self):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text("[]", encoding="utf-8")
        store = self.store()
        with self.assertRaises(SessionStoreError):
            store.list()
        with self.assertRaises(SessionStoreError):
            store.insert(_make_session())
        self.assertEqual(self.store_path.read_text(), "[]")

    def test_non_object_session_entry_raises_and_leaves_file_untouched(self):
        before = self._seed({
            "schemaVersion": 1,
            "revision": 1,
            "sessions": ["not-an-object"],
        })
        store = self.store()
        with self.assertRaises(SessionStoreError):
            store.list()
        with self.assertRaises(SessionStoreError):
            store.insert(_make_session())
        self.assertEqual(self.store_path.read_text(), before)

    def test_unknown_schema_version_raises_and_leaves_file_untouched(self):
        before = self._seed({"schemaVersion": 2, "revision": 1, "sessions": []})
        store = self.store()
        with self.assertRaises(SessionStoreError):
            store.list()
        with self.assertRaises(SessionStoreError):
            store.insert(_make_session())
        self.assertEqual(self.store_path.read_text(), before)


if __name__ == "__main__":
    unittest.main()
