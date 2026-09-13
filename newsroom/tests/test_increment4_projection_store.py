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
