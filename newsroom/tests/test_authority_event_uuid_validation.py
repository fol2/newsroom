from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

import pytest

from newsroom.authority._event_store_payload_integrity import (
    _PayloadAndEnvelopeIntegrity,
)
from newsroom.authority.persistence import AuthorityPersistenceError, PayloadId
from newsroom.authority.types import (
    AggregateId,
    AuthenticationContextId,
    AuthorizationDecisionId,
    CommandId,
    EventId,
    UUIDv4Id,
)

from .authority_event_helpers import open_test_system
from .authority_helpers import command, proof


UUID_FIELDS = (
    ("event_id", EventId),
    ("command_id", CommandId),
    ("payload_id", PayloadId),
    ("aggregate_id", AggregateId),
    ("authentication_context_id", AuthenticationContextId),
    ("authorization_decision_id", AuthorizationDecisionId),
)
VALID_UUID = "12345678-9abc-4def-8123-456789abcdef"


class UUIDText:
    def __str__(self):
        return VALID_UUID


@pytest.fixture(scope="module")
def event_row(tmp_path_factory):
    with open_test_system(
        tmp_path_factory.mktemp("event-uuid") / "authority.sqlite3"
    ) as system:
        system.commands.execute(command(), proof=proof())
        return asdict(system.events.after(0, proof=proof())[0])


def test_event_uuid_validation_does_not_construct_discarded_typed_ids(
    event_row, monkeypatch
):
    calls = []
    original = UUIDv4Id.parse.__func__

    def parse(cls, value):
        calls.append(cls.__name__)
        return original(cls, value)

    monkeypatch.setattr(UUIDv4Id, "parse", classmethod(parse))
    _PayloadAndEnvelopeIntegrity._validate_event_types(event_row)

    assert calls == []


@pytest.mark.parametrize("field,identifier_type", UUID_FIELDS)
@pytest.mark.parametrize(
    "value",
    [
        VALID_UUID,
        "00000000-0000-4000-8000-000000000000",
        "ffffffff-ffff-4fff-bfff-ffffffffffff",
        *(VALID_UUID[:19] + digit + VALID_UUID[20:] for digit in "89ab"),
        *(VALID_UUID[:14] + digit + VALID_UUID[15:] for digit in "012356789abcdef"),
        *(VALID_UUID[:19] + digit + VALID_UUID[20:] for digit in "01234567cdef"),
        VALID_UUID.upper(),
        " " + VALID_UUID,
        VALID_UUID + " ",
        VALID_UUID + "\n",
        VALID_UUID + "\r\n",
        VALID_UUID.replace("-", ""),
        "{" + VALID_UUID + "}",
        "urn:uuid:" + VALID_UUID,
        VALID_UUID[:-1],
        VALID_UUID + "0",
        "g" + VALID_UUID[1:],
        "１" + VALID_UUID[1:],
        "not-a-uuid",
        "",
        None,
        123,
        True,
        VALID_UUID.encode(),
        UUID(VALID_UUID),
        UUIDText(),
    ],
)
def test_event_uuid_validation_matches_typed_parse(
    event_row, field, identifier_type, value
):
    row = {**event_row, field: value}
    try:
        identifier_type.parse(str(value))
    except Exception as expected:
        with pytest.raises(type(expected)) as actual:
            _PayloadAndEnvelopeIntegrity._validate_event_types(row)
        assert str(actual.value) == str(expected)
    else:
        _PayloadAndEnvelopeIntegrity._validate_event_types(row)


@pytest.mark.parametrize("position", range(len(UUID_FIELDS)))
def test_event_uuid_validation_preserves_failure_order(event_row, position):
    field, identifier_type = UUID_FIELDS[position]
    row = dict(event_row)
    row[field] = VALID_UUID.upper()
    for later_field, _ in UUID_FIELDS[position + 1:]:
        row[later_field] = "not-a-uuid"
    row["recorded_at"] = "not-a-timestamp"
    with pytest.raises(Exception) as expected:
        identifier_type.parse(VALID_UUID.upper())
    with pytest.raises(type(expected.value)) as actual:
        _PayloadAndEnvelopeIntegrity._validate_event_types(row)
    assert str(actual.value) == str(expected.value)


def test_event_uuid_validation_preserves_initial_sequence_check(event_row):
    with pytest.raises(AuthorityPersistenceError, match="must be positive"):
        _PayloadAndEnvelopeIntegrity._validate_event_types(
            {**event_row, "ledger_seq": 0, "event_id": "not-a-uuid"}
        )


def test_event_uuid_validation_preserves_optional_typed_checks(
    event_row, monkeypatch
):
    calls = []
    original = UUIDv4Id.parse.__func__

    def parse(cls, value):
        calls.append(cls.__name__)
        return original(cls, value)

    monkeypatch.setattr(UUIDv4Id, "parse", classmethod(parse))
    row = {
        **event_row,
        "correlation_id": VALID_UUID,
        "causation_kind": "EVENT",
        "causation_identifier": VALID_UUID,
        "causation_external_system": None,
    }
    _PayloadAndEnvelopeIntegrity._validate_event_types(row)
    assert calls == ["CorrelationId", "EventId"]

    with pytest.raises(ValueError, match="identifier"):
        _PayloadAndEnvelopeIntegrity._validate_event_types(
            {**row, "correlation_id": VALID_UUID.upper()}
        )
    with pytest.raises(ValueError, match="identifier"):
        _PayloadAndEnvelopeIntegrity._validate_event_types(
            {**row, "causation_identifier": VALID_UUID.upper()}
        )
