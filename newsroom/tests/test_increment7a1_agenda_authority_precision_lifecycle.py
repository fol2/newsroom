from __future__ import annotations

import json
import uuid

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment7.agenda import (
    NO_CLOCK_GENERATED_EDITORIAL_RECORD,
    AgendaContractError,
    AgendaKind,
    AgendaPathKind,
    AgendaPathReference,
    AgendaResolutionKind,
    AgendaScheduleStatus,
    AgendaTimePrecision,
    AgendaUrgency,
    CoverageBasis,
    PlannedAgendaItem,
    PlannedAgendaVersion,
    validate_agenda_successor,
)


def _id(value: int) -> str:
    return str(uuid.UUID(int=value, version=4))


def _path(kind: AgendaPathKind, value: int) -> AgendaPathReference:
    return AgendaPathReference(
        kind=kind,
        source_definition_version_id=_id(value),
        path_policy_version="agenda-path-v1",
        rights_reference="rights-fixture-v1",
    )


def _version(**changes: object) -> PlannedAgendaVersion:
    values: dict[str, object] = {
        "agenda_version_id": _id(11),
        "agenda_item_id": _id(10),
        "version_ordinal": 1,
        "predecessor_version_digest": None,
        "source_revision_id": _id(12),
        "coverage_basis": CoverageBasis.PLANNED_AGENDA,
        "expected_subject": "Monetary Policy Committee decision",
        "time_precision": AgendaTimePrecision.EXACT_WINDOW,
        "asserted_start": "2026-09-01T11:00:00.000000Z",
        "asserted_end": "2026-09-01T12:00:00.000000Z",
        "time_zone": "Europe/London",
        "schedule_status": AgendaScheduleStatus.CONFIRMED,
        "expectation_path": _path(AgendaPathKind.EXPECTATION, 13),
        "occurrence_confirmation_paths": (
            _path(AgendaPathKind.OCCURRENCE_CONFIRMATION, 14),
            _path(AgendaPathKind.OCCURRENCE_CONFIRMATION, 15),
        ),
        "geography": "United Kingdom",
        "urgency": AgendaUrgency.TIME_SENSITIVE,
        "relationship_references": (),
        "uncertainties": (),
        "recorded_at": "2026-08-14T00:00:00.000000Z",
    }
    values.update(changes)
    return PlannedAgendaVersion(**values)  # type: ignore[arg-type]


def test_item_and_version_are_canonical_stable_and_round_trip() -> None:
    item = PlannedAgendaItem(
        agenda_item_id=_id(10),
        agenda_kind=AgendaKind.RELEASE,
        stable_subject_key="uk.mpc.decision.2026-09",
        created_from_source_revision_id=_id(12),
        created_at="2026-08-14T00:00:00.000000Z",
    )
    version = _version()

    assert PlannedAgendaItem.from_canonical_bytes(item.canonical_bytes) == item
    assert PlannedAgendaVersion.from_canonical_bytes(version.canonical_bytes) == version
    assert item.digest.startswith("sha256:")
    assert version.digest.startswith("sha256:")
    assert version.canonical_bytes == canonical_json_bytes(
        json.loads(version.canonical_bytes)
    )


@pytest.mark.parametrize(
    ("precision", "start", "end", "zone"),
    [
        (
            AgendaTimePrecision.EXACT_INSTANT,
            "2026-09-01T11:00:00.000000Z",
            None,
            "Europe/London",
        ),
        (AgendaTimePrecision.DATE_ONLY, "2026-09-01", None, "Europe/London"),
        (AgendaTimePrecision.APPROXIMATE, "early September 2026", None, None),
        (AgendaTimePrecision.TIME_ZONE_AMBIGUOUS, "2026-09-01 11:00", None, None),
        (AgendaTimePrecision.UNKNOWN, None, None, None),
    ],
)
def test_time_precision_preserves_the_exact_asserted_uncertainty(
    precision: AgendaTimePrecision,
    start: str | None,
    end: str | None,
    zone: str | None,
) -> None:
    value = _version(
        time_precision=precision,
        asserted_start=start,
        asserted_end=end,
        time_zone=zone,
    )
    assert value.time_precision is precision
    assert value.asserted_start == start
    assert value.time_zone == zone


@pytest.mark.parametrize(
    "changes",
    [
        {
            "time_precision": AgendaTimePrecision.EXACT_INSTANT,
            "asserted_end": "2026-09-01T12:00:00.000000Z",
        },
        {
            "time_precision": AgendaTimePrecision.EXACT_WINDOW,
            "asserted_end": "2026-09-01T10:00:00.000000Z",
        },
        {
            "time_precision": AgendaTimePrecision.DATE_ONLY,
            "asserted_start": "2026-09-01T11:00:00.000000Z",
            "asserted_end": None,
        },
        {
            "time_precision": AgendaTimePrecision.TIME_ZONE_AMBIGUOUS,
            "time_zone": "Europe/London",
            "asserted_end": None,
        },
        {
            "time_precision": AgendaTimePrecision.UNKNOWN,
            "asserted_start": "soon",
            "asserted_end": None,
            "time_zone": None,
        },
    ],
)
def test_time_precision_cannot_be_silently_widened(changes: dict[str, object]) -> None:
    with pytest.raises(AgendaContractError):
        _version(**changes)


def test_active_version_has_dual_distinct_paths_and_no_editorial_effect() -> None:
    version = _version()
    assert version.expectation_path.kind is AgendaPathKind.EXPECTATION
    assert all(
        path.kind is AgendaPathKind.OCCURRENCE_CONFIRMATION
        for path in version.occurrence_confirmation_paths
    )
    assert NO_CLOCK_GENERATED_EDITORIAL_RECORD.endswith(
        "NO_SIGNAL_LEAD_CANDIDATE_OR_EVIDENCE"
    )
    for value in (version, version.expectation_path):
        assert value.creates_signal is False
        assert value.creates_lead is False
        assert value.creates_candidate is False
        assert value.authorises_evidence is False
        assert value.authorises_schedule is False
        assert value.authorises_external_effect is False


def test_reschedule_is_an_exact_successor_and_preserves_prior_bytes() -> None:
    prior = _version()
    prior_bytes = prior.canonical_bytes
    successor = _version(
        agenda_version_id=_id(21),
        version_ordinal=2,
        predecessor_version_digest=prior.digest,
        asserted_start="2026-09-02T11:00:00.000000Z",
        asserted_end="2026-09-02T12:00:00.000000Z",
        recorded_at="2026-08-15T00:00:00.000000Z",
    )
    validate_agenda_successor(prior, successor)
    assert prior.canonical_bytes == prior_bytes
    assert successor.predecessor_version_digest == prior.digest

    bookkeeping_only = _version(
        agenda_version_id=_id(22),
        version_ordinal=2,
        predecessor_version_digest=prior.digest,
        recorded_at="2026-08-15T00:00:00.000000Z",
    )
    with pytest.raises(AgendaContractError, match="substantive source assertion"):
        validate_agenda_successor(prior, bookkeeping_only)


def test_successor_rejects_cross_item_gap_and_wrong_predecessor() -> None:
    prior = _version()
    for changes in (
        {"agenda_item_id": _id(99)},
        {"version_ordinal": 3},
        {"predecessor_version_digest": "sha256:" + "0" * 64},
    ):
        values: dict[str, object] = {
            "agenda_version_id": _id(21),
            "version_ordinal": 2,
            "predecessor_version_digest": prior.digest,
        }
        values.update(changes)
        successor = _version(**values)
        with pytest.raises(AgendaContractError, match="exact prior"):
            validate_agenda_successor(prior, successor)


def test_cancellation_postponement_and_withdrawal_require_source_uncertainty() -> None:
    for status in (
        AgendaScheduleStatus.CANCELLED,
        AgendaScheduleStatus.POSTPONED_WITHOUT_DATE,
        AgendaScheduleStatus.WITHDRAWN,
    ):
        with pytest.raises(AgendaContractError, match="source uncertainty"):
            _version(schedule_status=status)
        value = _version(
            schedule_status=status,
            uncertainties=("source-revision-asserted-status",),
        )
        assert value.schedule_status is status


def test_resolution_vocabulary_keeps_miss_failure_and_late_occurrence_distinct() -> (
    None
):
    assert {
        AgendaResolutionKind.MISSED_NOT_OBSERVED,
        AgendaResolutionKind.LATE_OCCURRENCE,
        AgendaResolutionKind.CHECK_FAILED,
        AgendaResolutionKind.CHECK_PARTIAL,
        AgendaResolutionKind.CHECK_UNAVAILABLE,
        AgendaResolutionKind.CANCELLED_WITH_SOURCE_EVIDENCE,
    } <= set(AgendaResolutionKind)
    assert (
        AgendaResolutionKind.MISSED_NOT_OBSERVED.value
        != AgendaResolutionKind.CANCELLED_WITH_SOURCE_EVIDENCE.value
    )


def test_parser_rejects_noncanonical_duplicate_unknown_and_oversized_values() -> None:
    version = _version()
    pretty = json.dumps(json.loads(version.canonical_bytes), indent=2).encode()
    with pytest.raises(AgendaContractError, match="exact canonical JSON"):
        PlannedAgendaVersion.from_canonical_bytes(pretty)
    duplicate = (
        version.canonical_bytes.decode()
        .replace(
            '"agenda_item_id":',
            '"agenda_item_id":"' + _id(99) + '","agenda_item_id":',
            1,
        )
        .encode()
    )
    with pytest.raises(AgendaContractError, match="duplicate object name"):
        PlannedAgendaVersion.from_canonical_bytes(duplicate)
    unknown = json.loads(version.canonical_bytes)
    unknown["creates_candidate"] = False
    with pytest.raises(AgendaContractError, match="fields are not exact"):
        PlannedAgendaVersion.from_canonical_bytes(canonical_json_bytes(unknown))
    with pytest.raises(AgendaContractError, match="bounded canonical text"):
        _version(expected_subject="x" * 2049)
    with pytest.raises(AgendaContractError, match="closed vocabulary"):
        _version(time_precision="WIDENED")
    with pytest.raises(AgendaContractError, match="date-only"):
        _version(
            time_precision=AgendaTimePrecision.DATE_ONLY,
            asserted_start="2026-02-30",
            asserted_end=None,
        )
    with pytest.raises(AgendaContractError, match="exact UTC timestamp"):
        _version(asserted_start="2026-02-30T11:00:00.000000Z")
    with pytest.raises(AgendaContractError, match="expectation path"):
        _version(expectation_path=object())


def test_occurrence_paths_are_nonempty_unique_sorted_and_do_not_create_occurrence() -> (
    None
):
    with pytest.raises(AgendaContractError, match="bounded confirmation paths"):
        _version(occurrence_confirmation_paths=())
    path = _path(AgendaPathKind.OCCURRENCE_CONFIRMATION, 14)
    with pytest.raises(AgendaContractError, match="unique and sorted"):
        _version(occurrence_confirmation_paths=(path, path))
    version = _version()
    assert version.creates_occurrence is False
