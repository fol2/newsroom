"""Canonical retry-forbidden safety state: 13361 available_at is observation only."""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.control_plane.issue_790_canary import (
    RetryForbiddenSafetyError,
    RetryForbiddenSafetyState,
    evaluate_retry_forbidden_safety,
    retry_forbidden_observation,
    retry_forbidden_safety_states_match,
    validate_retry_forbidden_safety_state,
)
from newsroom.control_plane.issue_790_disposition import (
    ISSUE_790_STEP22_PENDING_PLAN_PATH,
    Issue790DispositionError,
    qualify_issue_790_candidate_event,
)

_ROOT = Path(__file__).resolve().parents[2]
_EVENT_13361 = "sha256:90c3b4de731f2df8d4353e516762f65450570e1e8372ed7b703423f717351ae7"
_EVENT_13665 = "sha256:b39a1e6ea465ca4a993893d4ae51c94ca9ac3e0db7f4fd70a8c780367263be6b"
_SEALED_13361_AVAILABLE_AT = "2026-08-30T20:58:43.662872Z"
_LIVE_13361_AVAILABLE_AT = "2026-08-30T21:29:18.946358Z"
_SAFETY_FIELDS = (
    "event_id",
    "ledger_seq",
    "state",
    "attempt_count",
    "last_failure_code",
    "provider_dispatched",
)


def _plan() -> dict[str, object]:
    return json.loads((_ROOT / ISSUE_790_STEP22_PENDING_PLAN_PATH).read_text())


def _retry_events() -> list[dict[str, object]]:
    return [dict(item) for item in _plan()["retry_forbidden_events"]]


def _event(events: list[dict[str, object]], ledger_seq: int) -> dict[str, object]:
    return next(item for item in events if item["ledger_seq"] == ledger_seq)


def _live_13361() -> dict[str, object]:
    live = dict(_event(_retry_events(), 13361))
    live["available_at"] = _LIVE_13361_AVAILABLE_AT
    return live


def test_classification_is_predispatch_binding_failure() -> None:
    assert RetryForbiddenSafetyError.classification == "PREDISPATCH_BINDING_FAILURE"
    assert RetryForbiddenSafetyError.failure_code == "RETRY_FORBIDDEN_SAFETY_STATE"
    assert (
        evaluate_retry_forbidden_safety
        is validate_retry_forbidden_safety_state
    )


def test_preflight_and_live_apply_share_the_safety_state_validator() -> None:
    import inspect

    from newsroom.control_plane import issue_790_disposition as disposition
    from scripts.issue_790_live_canary_preflight import (
        _effective_retry_exclusion_status,
    )

    preflight_src = inspect.getsource(_effective_retry_exclusion_status)
    apply_src = inspect.getsource(disposition._require_retry_events_unchanged)
    exclusion_src = inspect.getsource(disposition._require_retry_exclusions)
    canary_src = inspect.getsource(disposition.run_issue_790_canary)
    assert "validate_retry_forbidden_safety_state" in preflight_src
    assert "retry_forbidden_safety_states_match" in preflight_src
    assert "retry_forbidden_safety_states_match" in apply_src
    assert "retry_forbidden_safety_states_match" in exclusion_src
    assert "event_snapshot\") == next(" not in preflight_src
    assert "_retain_retry_exclusions_for_plan" in canary_src
    assert "_require_retry_exclusions(" not in canary_src


def test_safety_state_fields_exclude_available_at_and_claims() -> None:
    names = tuple(item.name for item in fields(RetryForbiddenSafetyState))
    assert names == _SAFETY_FIELDS
    sealed = _event(_retry_events(), 13361)
    state = RetryForbiddenSafetyState.from_mapping(sealed)
    assert not hasattr(state, "available_at")
    observation = retry_forbidden_observation(_live_13361())
    assert observation["available_at"] == _LIVE_13361_AVAILABLE_AT
    assert observation["claim_owner"] is None
    assert observation["claim_expires_at"] is None
    assert "available_at" not in names


def test_green_13361_sealed_versus_live_available_at_with_equal_safety() -> None:
    sealed = _event(_retry_events(), 13361)
    live = _live_13361()
    assert sealed["available_at"] == _SEALED_13361_AVAILABLE_AT
    assert live["available_at"] == _LIVE_13361_AVAILABLE_AT
    assert sealed["available_at"] != live["available_at"]
    retained = validate_retry_forbidden_safety_state(
        expected=sealed, live=live, excluded=True
    )
    assert retained == RetryForbiddenSafetyState.from_mapping(sealed)
    assert retry_forbidden_safety_states_match(
        (sealed,), (live,), excluded_seqs=frozenset({13361})
    )
    observation = retry_forbidden_observation(live)
    assert observation["available_at"] == _LIVE_13361_AVAILABLE_AT
    assert observation["ledger_seq"] == 13361
    assert observation["event_id"] == _EVENT_13361


def test_green_retry_held_and_unparseable_available_at_are_observation_only() -> None:
    sealed = _event(_retry_events(), 1932)
    live = dict(sealed)
    live["available_at"] = _LIVE_13361_AVAILABLE_AT
    assert sealed["state"] == "RETRY_HELD"
    validate_retry_forbidden_safety_state(expected=sealed, live=live, excluded=True)
    broken = dict(_live_13361())
    broken["available_at"] = "not-a-time"
    validate_retry_forbidden_safety_state(
        expected=_event(_retry_events(), 13361), live=broken, excluded=True
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("event_id", _EVENT_13665),
        ("ledger_seq", 13665),
        ("state", "QUEUED"),
        ("attempt_count", 2),
        (
            "last_failure_code",
            "BOUNDED_CANARY_AUTHORITY_EXHAUSTED:PRODUCER_INTERNAL_ERROR",
        ),
        ("provider_dispatched", False),
    ),
)
def test_red_independent_safety_field_mutation(field: str, value: object) -> None:
    sealed = _event(_retry_events(), 13361)
    live = _live_13361()
    live[field] = value
    with pytest.raises(RetryForbiddenSafetyError, match="safety state differs"):
        validate_retry_forbidden_safety_state(expected=sealed, live=live, excluded=True)
    assert retry_forbidden_safety_states_match((sealed,), (live,)) is False


def test_red_missing_exclusion_membership() -> None:
    sealed = _event(_retry_events(), 13361)
    live = _live_13361()
    with pytest.raises(RetryForbiddenSafetyError, match="exclusion is absent"):
        validate_retry_forbidden_safety_state(expected=sealed, live=live, excluded=False)
    assert (
        retry_forbidden_safety_states_match(
            (sealed,), (live,), excluded_seqs=frozenset()
        )
        is False
    )


def test_red_claim_or_lease_is_present() -> None:
    sealed = _event(_retry_events(), 13361)
    claimed = _live_13361()
    claimed["claim_owner"] = "issue-790-canary:test"
    with pytest.raises(RetryForbiddenSafetyError, match="claim/lease is present"):
        validate_retry_forbidden_safety_state(expected=sealed, live=claimed, excluded=True)
    leased = _live_13361()
    leased["claim_expires_at"] = "2026-08-31T12:00:00.000000Z"
    with pytest.raises(RetryForbiddenSafetyError, match="claim/lease is present"):
        validate_retry_forbidden_safety_state(expected=sealed, live=leased, excluded=True)
    live = _live_13361()
    live["claim_owner"] = None
    live["claim_expires_at"] = None
    validate_retry_forbidden_safety_state(expected=sealed, live=live, excluded=True)
    assert retry_forbidden_safety_states_match((sealed,), (live,)) is True


def test_red_missing_row() -> None:
    sealed = _event(_retry_events(), 13361)
    with pytest.raises(RetryForbiddenSafetyError, match="row is absent"):
        validate_retry_forbidden_safety_state(expected=sealed, live=None, excluded=True)


def test_event_13665_is_unused_target_and_not_retry_forbidden() -> None:
    plan = _plan()
    seqs = [item["ledger_seq"] for item in plan["retry_forbidden_events"]]
    ids = [item["event_id"] for item in plan["retry_forbidden_events"]]
    assert 13665 not in seqs
    assert _EVENT_13665 not in ids
    qualification = plan["sequence"]["candidate_event_qualification"]
    assert qualification["event_id"] == _EVENT_13665
    assert qualification["ledger_seq"] == 13665
    assert qualification["provider_calls"] == 0
    assert qualification["store_mutations"] == 0
    assert plan["executable"] is False
    assert plan["live_canary_authorised"] is False


def test_13665_machine_qualification_without_mini_store_stops(
    tmp_path: Path,
) -> None:
    with pytest.raises(Issue790DispositionError, match="source unpublished store is absent"):
        qualify_issue_790_candidate_event(
            store=tmp_path / "missing.sqlite3",
            proving_store=tmp_path / "missing-proving.sqlite3",
            event_id=_EVENT_13665,
            ledger_seq=13665,
            observed_at=datetime(2026, 8, 31, 10, 12, tzinfo=UTC),
        )
    plan = _plan()
    seqs = [item["ledger_seq"] for item in plan["retry_forbidden_events"]]
    ids = [item["event_id"] for item in plan["retry_forbidden_events"]]
    assert 13665 not in seqs
    assert _EVENT_13665 not in ids
    qualification = plan["sequence"]["candidate_event_qualification"]
    assert qualification["event_id"] == _EVENT_13665
    assert qualification["ledger_seq"] == 13665
    assert qualification["provider_calls"] == 0
    assert qualification["store_mutations"] == 0
    assert plan["executable"] is False
    assert plan["live_canary_authorised"] is False


def test_safety_evaluation_does_not_dispatch_or_mutate_13665(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def _refuse(*_args: object, **_kwargs: object) -> None:
        calls.append(1)
        raise AssertionError("provider dispatch is forbidden")

    monkeypatch.setattr(
        "newsroom.control_plane.graphiti_events.dispatch_graphiti_event",
        _refuse,
        raising=False,
    )
    validate_retry_forbidden_safety_state(
        expected=_event(_retry_events(), 13361),
        live=_live_13361(),
        excluded=True,
    )
    assert calls == []
    assert 13665 not in {
        item["ledger_seq"] for item in _retry_events()
    }
