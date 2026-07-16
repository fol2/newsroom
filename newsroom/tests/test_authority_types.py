from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid1

import pytest

from newsroom.authority import (
    AggregateId,
    AggregateVersion,
    CanonicalizationError,
    CommandId,
    TemporalValue,
    TimePrecision,
    TrustScope,
    UtcTimestamp,
    canonical_json_bytes,
    digest_canonical,
)
from newsroom.authority.types import AuthorityTypeError


def test_typed_uuidv4_roundtrip_and_type_separation() -> None:
    aggregate_id = AggregateId.new()

    assert str(AggregateId.parse(str(aggregate_id))) == str(aggregate_id)
    assert AggregateId.parse(str(aggregate_id)) == aggregate_id
    assert CommandId(aggregate_id.value) != aggregate_id


def test_typed_id_rejects_non_v4_and_noncanonical_text() -> None:
    with pytest.raises(AuthorityTypeError):
        AggregateId(uuid1())

    value = str(AggregateId.new())
    with pytest.raises(AuthorityTypeError):
        AggregateId.parse(value.upper())
    with pytest.raises(AuthorityTypeError):
        AggregateId.parse(value.replace("-", ""))


def test_aggregate_version_is_positive() -> None:
    assert int(AggregateVersion(1)) == 1
    with pytest.raises(AuthorityTypeError):
        AggregateVersion(0)
    with pytest.raises(AuthorityTypeError):
        AggregateVersion(True)


def test_utc_timestamp_normalises_offset_and_rejects_naive() -> None:
    local = datetime(2026, 7, 16, 20, 0, tzinfo=UTC) + timedelta(hours=1)
    timestamp = UtcTimestamp(local)

    assert timestamp.value.tzinfo is UTC
    assert timestamp.to_text().endswith("Z")
    assert UtcTimestamp.parse(timestamp.to_text()) == timestamp

    with pytest.raises(AuthorityTypeError):
        UtcTimestamp(datetime(2026, 7, 16, 20, 0))


def test_temporal_values_preserve_precision_and_conflict() -> None:
    exact = TemporalValue(
        datetime(2026, 7, 16, 12, 30, tzinfo=UTC), TimePrecision.EXACT
    )
    date_only = TemporalValue(date(2026, 7, 16), TimePrecision.DATE_ONLY)
    unknown = TemporalValue(None, TimePrecision.UNKNOWN)
    conflicting = TemporalValue(
        None,
        TimePrecision.CONFLICTING,
        ("2026-07-16T10:00:00Z", "2026-07-16T11:00:00Z"),
    )

    assert exact.value == datetime(2026, 7, 16, 12, 30, tzinfo=UTC)
    assert date_only.value == date(2026, 7, 16)
    assert unknown.value is None
    assert len(conflicting.conflicting_values) == 2

    with pytest.raises(AuthorityTypeError):
        TemporalValue(None, TimePrecision.EXACT)
    with pytest.raises(AuthorityTypeError):
        TemporalValue(None, TimePrecision.CONFLICTING, ("only-one",))


def test_canonical_json_is_order_stable_and_restricted() -> None:
    left = {"b": [2, 1], "a": "值", "trust": TrustScope.OBSERVED.value}
    right = {"trust": "OBSERVED", "a": "值", "b": [2, 1]}

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert digest_canonical(left) == digest_canonical(right)

    with pytest.raises(CanonicalizationError):
        canonical_json_bytes({"float": 1.25})
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes({"too_large": 9_007_199_254_740_992})
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes({"bad": "\ud800"})
