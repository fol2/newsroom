from __future__ import annotations

from contextlib import nullcontext

import pytest

from newsroom.authority._event_store_read import _EventStoreReadMixin
from newsroom.authority._increment4_projection_store import (
    _Increment4ProjectionAuthorityStore,
)
from newsroom.authority.persistence import AuthorityPersistenceError


def _event_row(ledger_seq: object) -> dict[str, object]:
    suffix = str(ledger_seq)
    return {
        "ledger_seq": ledger_seq,
        "event_id": f"event-{suffix}",
        "event_type": "source.item.versioned",
        "event_schema_version": 1,
        "aggregate_type": "source-item",
        "aggregate_id": f"item-{suffix}",
        "aggregate_version": 1,
        "recorded_at": "2026-09-13T12:00:00.000000Z",
        "command_id": f"command-{suffix}",
        "producer_version": "fixture-v1",
        "command_definition_version": "fixture-command-v1",
        "command_definition_digest": "sha256:" + "1" * 64,
        "payload_id": f"payload-{suffix}",
        "payload_mode": "INLINE",
        "payload_schema_version": "fixture-schema-v1",
        "payload_schema_contract_version": "fixture-contract-v1",
        "payload_schema_contract_digest": "sha256:" + "2" * 64,
        "payload_canonicalizer_version": "canonical-json-v1",
        "payload_digest": "sha256:" + "3" * 64,
        "object_admission_id": None,
        "principal_id": "fixture-principal",
        "authentication_context_id": "fixture-authentication",
        "authorization_request_digest": "sha256:" + "4" * 64,
        "authorization_decision_id": f"decision-{suffix}",
        "correlation_id": None,
        "causation_kind": None,
        "causation_identifier": None,
        "causation_external_system": None,
        "security_scope": "INTERNAL",
        "retention_scope": "PERMANENT",
        "trust_scope": "VERIFIED",
    }


class _Rows:
    def __init__(self, rows, *, forbid_fetchall: bool = False):
        self._rows = tuple(rows)
        self._forbid_fetchall = forbid_fetchall

    def __iter__(self):
        return iter(self._rows)

    def fetchall(self):
        if self._forbid_fetchall:
            raise AssertionError("snapshot ledger events must be decoded while streaming")
        return list(self._rows)


class _Connection:
    def __init__(self, events):
        self._events = events

    def execute(self, sql, _parameters=()):
        statement = " ".join(sql.split())
        if statement.startswith("SELECT p.entity_id"):
            return _Rows(())
        if statement.startswith("SELECT assertion_id"):
            return _Rows(())
        if statement.startswith("SELECT * FROM ledger_events"):
            return _Rows(self._events, forbid_fetchall=True)
        raise AssertionError(f"unexpected snapshot query: {statement}")


class _Store:
    _increment4_admitted_states = _Increment4ProjectionAuthorityStore._increment4_admitted_states
    _lock = nullcontext()
    _event_from_row = staticmethod(_EventStoreReadMixin._event_from_row)

    def __init__(self, events, watermark):
        self._connection = _Connection(events)
        self._watermark = watermark

    def latest_projection_source_ledger_seq(self):
        return self._watermark


def _snapshot(events, watermark):
    return _Increment4ProjectionAuthorityStore.increment4_admitted_snapshot(
        _Store(events, watermark)
    )


def test_increment4_snapshot_streams_complete_ordered_ledger_events() -> None:
    snapshot = _snapshot((_event_row(1), _event_row(2)), 2)

    assert tuple(event.ledger_seq for event in snapshot.events) == (1, 2)
    assert tuple(event.event_id for event in snapshot.events) == ("event-1", "event-2")
    assert snapshot.through_ledger_seq == 2
    assert snapshot.canonical_digest == (
        "sha256:cb0ee7f8c9b2731c52bd3a422fa2fd344020fe4f242512cd3f5ef6334331f154"
    )


def test_increment4_snapshot_rejects_missing_watermark_event() -> None:
    with pytest.raises(AuthorityPersistenceError, match="watermark lacks"):
        _snapshot((_event_row(1),), 2)


def test_increment4_snapshot_rejects_invalid_event() -> None:
    with pytest.raises(ValueError):
        _snapshot((_event_row("not-an-integer"),), 1)


def test_streamed_provenance_keeps_exact_full_history_digest_without_history_tuple():
    from newsroom.increment4.models import _stream_admitted_provenance

    rows = tuple(_event_row(seq) for seq in range(1, 1001))
    complete = _snapshot(rows, 1000)
    retained, digest = _stream_admitted_provenance(
        entities=(), relations=(),
        events=(_EventStoreReadMixin._event_from_row(row) for row in rows),
        through_ledger_seq=1000,
    )
    assert digest == complete.canonical_digest
    assert tuple(event.ledger_seq for event in retained.events) == (1000,)
    changed = [dict(row) for row in rows]
    changed[10]["payload_digest"] = "sha256:" + "9" * 64
    _, changed_digest = _stream_admitted_provenance(
        entities=(), relations=(),
        events=(_EventStoreReadMixin._event_from_row(row) for row in changed),
        through_ledger_seq=1000,
    )
    assert changed_digest != digest


@pytest.mark.parametrize("sequences", [(), (1,), (2, 1), (1, 1), (1, 3)])
def test_streamed_provenance_rejects_missing_watermark_and_unordered_history(sequences):
    from newsroom.increment4.models import _stream_admitted_provenance

    with pytest.raises(ValueError):
        _stream_admitted_provenance(
            entities=(), relations=(),
            events=(_EventStoreReadMixin._event_from_row(_event_row(seq)) for seq in sequences),
            through_ledger_seq=2,
        )


@pytest.mark.parametrize("mutation", ["append", "rewrite"])
def test_current_inputs_pin_one_sqlite_snapshot_and_release_it(tmp_path, mutation):
    import sqlite3
    from threading import RLock
    from newsroom.increment4 import increment4_admitted_contract_registry
    from newsroom.projection.models import ProjectionGenerationId

    path = tmp_path / "events.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    row = _event_row(1)
    connection.execute("CREATE TABLE ledger_events (" + ",".join(
        f'"{key}" ' + ("INTEGER" if isinstance(value, int) else "TEXT")
        for key, value in row.items()
    ) + ")")
    insert = "INSERT INTO ledger_events VALUES (" + ",".join("?" for _ in row) + ")"
    connection.executemany(insert, [tuple(_event_row(seq).values()) for seq in (1, 2)])
    writer = sqlite3.connect(path, isolation_level=None)

    class Store:
        _lock = RLock()
        _connection = connection
        _event_from_row = staticmethod(_EventStoreReadMixin._event_from_row)
        _increment4_projection_read = _Increment4ProjectionAuthorityStore._increment4_projection_read

        def _increment4_admitted_states(self):
            watermark = connection.execute("SELECT max(ledger_seq) FROM ledger_events").fetchone()[0]
            if mutation == "append":
                writer.execute(insert, tuple(_event_row(3).values()))
            else:
                writer.execute("UPDATE ledger_events SET payload_digest=? WHERE ledger_seq=1", ("sha256:" + "9" * 64,))
            return (), (), watermark

    try:
        inputs = _Increment4ProjectionAuthorityStore._increment4_current_build_inputs(
            Store(), generation_id=ProjectionGenerationId.parse("00000000-0000-4000-8000-000000004991"),
            family=increment4_admitted_contract_registry().family("graph.increment4.admitted"),
        )
        assert inputs.snapshot_digest == _snapshot((_event_row(1), _event_row(2)), 2).canonical_digest
        assert inputs.source_watermark == 2
        assert inputs.batches == ()
        assert not connection.in_transaction
        if mutation == "append":
            assert connection.execute("SELECT max(ledger_seq) FROM ledger_events").fetchone()[0] == 3
        else:
            assert connection.execute("SELECT payload_digest FROM ledger_events WHERE ledger_seq=1").fetchone()[0] == "sha256:" + "9" * 64
    finally:
        writer.close()
        connection.close()


@pytest.mark.parametrize("fail", [False, True])
def test_projection_read_preserves_outer_transaction(tmp_path, fail):
    import sqlite3
    from threading import RLock

    connection = sqlite3.connect(tmp_path / "outer.sqlite3", isolation_level=None)
    connection.execute("CREATE TABLE caller_work (value TEXT)")
    connection.execute("BEGIN")
    connection.execute("INSERT INTO caller_work VALUES ('uncommitted')")

    class Store:
        _lock = RLock()
        _connection = connection
        _event_from_row = staticmethod(_EventStoreReadMixin._event_from_row)

        def _increment4_admitted_states(self):
            if fail:
                raise ValueError("state invalid")
            return (), (), 1

    try:
        if fail:
            with pytest.raises(ValueError, match="state invalid"):
                with _Increment4ProjectionAuthorityStore._increment4_projection_read(Store()):
                    pytest.fail("invalid state was accepted")
        else:
            with _Increment4ProjectionAuthorityStore._increment4_projection_read(Store()):
                pass
        assert connection.in_transaction
        assert connection.execute("SELECT value FROM caller_work").fetchone()[0] == "uncommitted"
        connection.rollback()
        assert connection.execute("SELECT count(*) FROM caller_work").fetchone()[0] == 0
    finally:
        connection.close()


@pytest.mark.parametrize("hash_history", [False, True])
def test_provenance_stream_bounds_live_decoded_optional_events(hash_history):
    from weakref import WeakSet
    from newsroom.authority.persistence import LedgerEventRecord
    from newsroom.increment4.models import _stream_admitted_provenance

    class TrackedEvent(LedgerEventRecord):
        pass

    live = WeakSet()
    peak = 0

    def events():
        nonlocal peak
        for sequence in range(1, 1001):
            event = TrackedEvent(**_event_row(sequence))
            live.add(event)
            peak = max(peak, len(live))
            yield event

    provenance, digest = _stream_admitted_provenance(
        entities=(), relations=(), events=events(), through_ledger_seq=1000,
        hash_history=hash_history,
    )
    assert peak <= 3
    assert len(live) == len(provenance.events) == 1
    assert (digest is not None) is hash_history
