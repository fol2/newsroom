from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from newsroom.authority import (
    AggregateId,
    CausationKind,
    CausationRef,
    CommandId,
    CorrelationId,
    TemporalValue,
    TimePrecision,
    UtcTimestamp,
)
from newsroom.authority.types import AuthorityTypeError


def test_typed_uuid_identity_is_type_sensitive_and_non_ordering() -> None:
    aggregate = AggregateId.new()
    parsed = AggregateId.parse(str(aggregate))
    assert parsed == aggregate
    command_id = CommandId.parse(str(aggregate))
    assert command_id != aggregate
    with pytest.raises(TypeError):
        _ = aggregate < AggregateId.new()


def test_utc_and_temporal_values_are_explicit() -> None:
    stamp = UtcTimestamp(datetime(2026, 7, 16, 12, 0, tzinfo=UTC))
    assert UtcTimestamp.parse(stamp.to_text()) == stamp
    assert TemporalValue(date(2026, 7, 16), TimePrecision.DATE_ONLY).value == date(
        2026, 7, 16
    )
    assert TemporalValue(None, TimePrecision.UNKNOWN).value is None
    with pytest.raises(AuthorityTypeError):
        TemporalValue(None, TimePrecision.EXACT)


def test_correlation_and_causation_contracts_are_typed() -> None:
    correlation = CorrelationId.new()
    assert CorrelationId.parse(str(correlation)) == correlation
    command_id = CommandId.new()
    ref = CausationRef(CausationKind.COMMAND, str(command_id))
    assert ref.identifier == str(command_id)
    external = CausationRef(CausationKind.EXTERNAL, "delivery-42", "provider.api")
    assert external.external_system == "provider.api"
    with pytest.raises(AuthorityTypeError):
        CausationRef(CausationKind.COMMAND, "not-a-command-id")
