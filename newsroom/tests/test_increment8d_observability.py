from __future__ import annotations

import json
from dataclasses import replace

import pytest

from newsroom.increment8.observability import (
    AccessContract,
    AlertPriority,
    CoveragePath,
    CoveragePosture,
    CoverageVerdict,
    DimensionState,
    EventInputContract,
    HealthDimension,
    HealthPosture,
    HealthVerdict,
    IncidentRecord,
    IncidentState,
    ManualAction,
    ManualActionReceipt,
    ObservabilityError,
    ObservabilityRecord,
    ObservationOutcome,
    PathRole,
    SecurityAdmission,
    classify_transport_outcome,
)

_D = "sha256:" + "1" * 64
_D2 = "sha256:" + "2" * 64
_AT = "2042-01-05T00:00:00.000000Z"
_RECENT = "2042-01-04T23:59:00.000000Z"
_STALE = "2042-01-04T23:40:00.000000Z"


def _dimensions(state=DimensionState.HEALTHY):
    return {dimension.value: state for dimension in HealthDimension}


def _health(*, outcome=ObservationOutcome.COMPLETE_UNCHANGED, success=_RECENT, states=None):
    return HealthPosture.build(
        scope_id="fixture-source:one",
        dimension_states=_dimensions() if states is None else states,
        observation_outcome=outcome,
        last_complete_success_at=success,
        last_source_change_at="2042-01-01T00:00:00.000000Z",
        observed_at=_AT,
    )


def _access():
    return AccessContract.build(
        contract_id="fixture-access:v1",
        approved_hosts=["fixture.invalid"],
        maximum_redirects=0,
        request_timeout_seconds=30,
        maximum_body_bytes=1_000_000,
        content_types=["application/json", "application/xml"],
    )


def test_healthy_silence_requires_complete_success_and_uses_last_success_age() -> None:
    healthy = _health()
    assert healthy.verdict is HealthVerdict.HEALTHY_UNCHANGED
    assert healthy.complete_success_age_seconds == 60
    stale = _health(success=_STALE)
    assert stale.verdict is HealthVerdict.STALE
    assert stale.last_source_change_at != stale.last_complete_success_at


def test_freshness_uses_full_precision_before_rendering_integer_age() -> None:
    at_threshold = _health(success="2042-01-04T23:45:00.000000Z")
    just_over = _health(success="2042-01-04T23:44:59.999999Z")
    assert at_threshold.complete_success_age_seconds == 900
    assert at_threshold.verdict is HealthVerdict.HEALTHY_UNCHANGED
    assert just_over.complete_success_age_seconds == 900
    assert just_over.verdict is HealthVerdict.STALE


def test_failed_or_partial_observation_is_not_healthy_silence() -> None:
    assert _health(outcome=ObservationOutcome.FAILED).verdict is HealthVerdict.DEGRADED
    states = _dimensions()
    states[HealthDimension.AUTHORITY.value] = DimensionState.BLOCKED
    assert _health(states=states).verdict is HealthVerdict.BLOCKED


def test_comparator_cannot_substitute_for_failed_anchor() -> None:
    failed = _health(outcome=ObservationOutcome.FAILED)
    healthy = _health()
    posture = CoveragePosture.build(
        obligation_id="obligation:active",
        active=True,
        paths=[
            CoveragePath.build(path_id="anchor", role=PathRole.ANCHOR, health=failed, authority_current=True),
            CoveragePath.build(path_id="search", role=PathRole.COMPARATOR, health=healthy, authority_current=True),
        ],
        containment_policy_digest=_D,
    )
    assert posture.verdict is CoverageVerdict.COVERAGE_BLOCKED
    assert posture.containment_invoked is True
    assert json.loads(posture.canonical_bytes)["payload"]["comparator_substitution_allowed"] is False


def test_transport_status_and_shape_drift_retain_distinct_meanings() -> None:
    assert classify_transport_outcome(status_code=304, body_bytes=0, valid_baseline=True, validator_contract=True, shape_valid=True) == "COMPLETE_UNCHANGED"
    assert classify_transport_outcome(status_code=304, body_bytes=0, valid_baseline=False, validator_contract=True, shape_valid=True) == "INVALID_NOT_MODIFIED"
    assert classify_transport_outcome(status_code=200, body_bytes=0, valid_baseline=False, validator_contract=False, shape_valid=True) == "EMPTY_SUCCESS"
    assert classify_transport_outcome(status_code=200, body_bytes=10, valid_baseline=False, validator_contract=False, shape_valid=False) == "SHAPE_DRIFT_QUARANTINE"
    assert classify_transport_outcome(status_code=429, body_bytes=0, valid_baseline=False, validator_contract=False, shape_valid=True) == "RATE_LIMITED"
    assert classify_transport_outcome(status_code=206, body_bytes=10, valid_baseline=False, validator_contract=True, shape_valid=True) == "PARTIAL"


def test_access_contract_is_strict_and_contains_no_live_egress_or_credentials() -> None:
    contract = _access()
    payload = json.loads(contract.canonical_bytes)["payload"]
    assert payload["schemes"] == ["https"]
    assert payload["tls_verification_required"] is True
    assert payload["credential_references"] == payload["egress_destinations"] == 0
    assert payload["external_entity_resolution"] is False
    assert payload["untrusted_input_can_change_authority"] is False
    with pytest.raises(ObservabilityError, match="exceeds fixture bounds"):
        AccessContract.build(
            contract_id="fixture-access:bad", approved_hosts=["fixture.invalid"], maximum_redirects=0,
            request_timeout_seconds=31, maximum_body_bytes=1_000, content_types=["application/json"],
        )


def test_delivered_event_input_is_authenticated_replay_bounded_and_receipted() -> None:
    contract = EventInputContract.build(
        channel_id="fixture-channel:one",
        authentication_key_digest=_D,
        provenance_policy_digest=_D,
        replay_window_seconds=300,
        maximum_payload_bytes=100_000,
    )
    payload = json.loads(contract.canonical_bytes)["payload"]
    assert payload["durable_receipt_required"] is True
    assert payload["untrusted_payload_policy_authority"] is False
    assert payload["live_delivery_authorised"] is False


def test_observability_is_versioned_correlated_safe_and_consequence_prioritised() -> None:
    metrics = {name: 0 for name in ("budget", "complete_success_age", "coverage", "outcome", "parser", "queue", "reconciliation", "retry", "schedule", "storage")}
    correlation = {name: _D for name in ("candidate", "check", "due_trigger", "handoff", "lead", "transition", "work_item")}
    record = ObservabilityRecord.build(
        source_version_digest=_D, component_version_digest=_D, profile_digest=_D,
        provider_version_digest=_D, policy_version_digest=_D, metrics=metrics,
        path_correlation=correlation, coverage_blocked=True, integrity_uncertain=False, urgent=True,
        owner_digest=_D, escalation_digest=_D, runbook_version_digest=_D,
    )
    assert record.priority is AlertPriority.P1
    assert json.loads(record.canonical_bytes)["payload"]["prohibited_data_logged"] is False


def test_incident_lifecycle_is_append_only_and_integrity_close_requires_regression_case() -> None:
    opened = IncidentRecord.open(
        incident_id="incident:one", scope_digest=_D, opened_at=_AT, timeline_digest=_D,
        integrity_related=True, near_miss=False,
    )
    contained = opened.transition(state=IncidentState.CONTAINED, evidence_digest=_D)
    recovered = contained.transition(state=IncidentState.RECOVERED, evidence_digest=_D)
    with pytest.raises(ObservabilityError, match="regression_case_digest"):
        recovered.transition(state=IncidentState.CLOSED, evidence_digest=_D, root_cause_digest=_D, follow_up_digest=_D)
    closed = recovered.transition(
        state=IncidentState.CLOSED, evidence_digest=_D2, root_cause_digest=_D,
        follow_up_digest=_D, regression_case_digest=_D,
    )
    assert closed.previous_digest == recovered.digest
    assert closed.version == 4
    assert closed.closure_evidence_digest == _D2
    assert json.loads(closed.canonical_bytes)["payload"]["closure_evidence_digest"] == _D2
    alternate = recovered.transition(
        state=IncidentState.CLOSED, evidence_digest=_D, root_cause_digest=_D,
        follow_up_digest=_D, regression_case_digest=_D,
    )
    assert alternate.digest != closed.digest
    with pytest.raises(ObservabilityError, match="evidence_digest"):
        recovered.transition(
            state=IncidentState.CLOSED, evidence_digest="not-a-digest", root_cause_digest=_D,
            follow_up_digest=_D, regression_case_digest=_D,
        )


def test_incident_transition_reconstructs_exact_retained_record() -> None:
    opened = IncidentRecord.open(
        incident_id="incident:forged", scope_digest=_D, opened_at=_AT, timeline_digest=_D,
        integrity_related=True, near_miss=False,
    )
    contained = opened.transition(state=IncidentState.CONTAINED, evidence_digest=_D)
    recovered = contained.transition(state=IncidentState.RECOVERED, evidence_digest=_D)
    with pytest.raises(ObservabilityError, match="canonical"):
        replace(recovered, integrity_related=False).transition(
            state=IncidentState.CLOSED, evidence_digest=_D2, root_cause_digest=_D,
            follow_up_digest=_D, regression_case_digest=_D,
        )


def test_manual_actions_are_authenticated_audited_and_never_automatic() -> None:
    receipt = ManualActionReceipt.build(
        action=ManualAction.QUARANTINE_RELEASE, scope_digest=_D, actor_identity_digest=_D,
        authorisation_digest=_D, evidence_digest=_D, acted_at=_AT,
    )
    payload = json.loads(receipt.canonical_bytes)["payload"]
    assert payload["authenticated"] is payload["audited"] is True
    assert payload["automatic"] is False


def test_security_admission_is_exact_versioned_and_never_activation() -> None:
    blocked = SecurityAdmission.build(
        access_contract=_access(), exact_version_approved=False, rights_current=True,
        terms_current=True, pricing_current=True, credential_scope_current=True,
        rollback_tested=True, scoped_disable_tested=True, graph_capability_admitted=False,
        runbook_version_digest=_D,
    )
    assert blocked.eligible is False
    assert blocked.blocking_reasons == ("exact_version_approved", "graph_capability_admitted")
    payload = json.loads(blocked.canonical_bytes)["payload"]
    assert payload["canary_authorised"] is payload["production_activation_authorised"] is False
    assert payload["live_credentials"] == payload["network_egress_destinations"] == payload["external_spend_pence"] == 0
