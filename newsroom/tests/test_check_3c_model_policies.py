from __future__ import annotations

from dataclasses import replace
import json

import pytest

from newsroom.checks import (
    AbsenceEndingGuard,
    AgendaMissGuard,
    BaselineAction,
    BaselineControl,
    BaselineDecisionKind,
    BaselineDisposition,
    BaselineEntryDisposition,
    ObservableTransitionKind,
    ProposalAdmissionConflict,
    ProposalAdmissionRequest,
    TransitionBasis,
    TransitionDirective,
    TriggerKind,
    TriggerRef,
)
from newsroom.discovery_adapters import (
    AdapterKind,
    AdapterRequestId,
    ConditionalValidator,
    ObservationBaseline,
    ObservationProposalOutcome,
    ShapeField,
    SourceShapeContract,
    run_fixture_adapter,
)
from newsroom.sources import (
    BaselinePolicy,
    BaselinePolicyKind,
    ObservationModel,
    SourceRole,
    SourceRoleAssignment,
    VersionedPolicyRef,
)

from .check_3c_authority_helpers import (
    definition_request,
    open_check_system,
    proof,
    version_request,
)
from .check_3c_helpers import DIGEST_A, DIGEST_B, NOW
from .discovery_adapter_3b_helpers import request as adapter_request_fixture
from .test_check_3c_admission import (
    _admission,
    _check_records,
    _scenario,
)


_POLICY_KIND = {
    ObservationModel.MUTABLE_ITEM: BaselinePolicyKind.MAINTAINED_DOCUMENT,
    ObservationModel.APPEND_ONLY: BaselinePolicyKind.BOUNDED_BACKFILL,
    ObservationModel.ROLLING_LIST: BaselinePolicyKind.BOUNDED_BACKFILL,
    ObservationModel.COMPLETE_CURRENT_STATE: (
        BaselinePolicyKind.COMPLETE_STATE_FIRST_OBSERVED_ACTIVE
    ),
    ObservationModel.EXPLICIT_DELTA: BaselinePolicyKind.EXPLICIT_DELTA_SEQUENCE,
    ObservationModel.PLANNED_AGENDA: BaselinePolicyKind.PLANNED_AGENDA_FUTURE_ONLY,
}


def _shape(model: ObservationModel) -> SourceShapeContract:
    time_name = (
        "expected_time"
        if model is ObservationModel.PLANNED_AGENDA
        else "source_published_time"
    )
    fields = tuple(
        sorted(
            (
                ShapeField("id", ("id",), True),
                ShapeField(time_name, (time_name,), True),
                ShapeField("status", ("status",), True),
                ShapeField("title", ("title",), True),
            ),
            key=lambda item: item.name,
        )
    )
    return SourceShapeContract(
        shape_id=f"model-{model.value.lower()}-v1",
        kind=AdapterKind.JSON_DOCUMENT,
        items_path=("items",),
        fields=fields,
        identity_fields=("id",),
    )


def _model_version(model: ObservationModel):
    base = version_request()
    kind = _POLICY_KIND[model]
    roles = base.roles
    if model is ObservationModel.PLANNED_AGENDA:
        roles = (
            SourceRoleAssignment(
                role=SourceRole.PLANNED_AGENDA,
                purpose="Retain fixture future expectations without creating Leads.",
                limitations=("Fixture and approved replay only.",),
            ),
        )
    time_name = (
        "expected_time"
        if model is ObservationModel.PLANNED_AGENDA
        else "source_published_time"
    )
    return replace(
        base,
        extraction_scope=tuple(sorted(("id", time_name, "status", "title"))),
        roles=roles,
        observation_model=model,
        baseline_policy=BaselinePolicy(
            reference=VersionedPolicyRef("fixture-baseline", "v1"),
            kind=kind,
            freshness_window_seconds=(
                24 * 60 * 60
                if kind is BaselinePolicyKind.BOUNDED_BACKFILL
                else None
            ),
            reset_requires_decision=True,
            notes=f"Fixture {model.value} baseline.",
        ),
        change_reason=f"Fixture {model.value} source contract.",
        idempotency_key=f"fixture-{model.value.lower()}-source-version",
    )


def _adapter_request(
    model: ObservationModel,
    *,
    suffix: int,
    baseline: ObservationBaseline | None = None,
):
    base = adapter_request_fixture(
        kind=AdapterKind.JSON_DOCUMENT,
        observation_model=model,
        shape=_shape(model),
        baseline=baseline,
        allowed_content_types=("application/json",),
    )
    return replace(
        base,
        request_id=AdapterRequestId.parse(
            f"00000000-0000-4000-8000-{8000 + suffix:012d}"
        ),
        source_definition_id=definition_request().definition_id,
        source_definition_version_id=version_request().version_id,
        requested_at=NOW,
    )


def _body(items: list[dict[str, str]]) -> bytes:
    return json.dumps(
        {"items": items},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _proposal(adapter_request, *, suffix: int, items: list[dict[str, str]]):
    return run_fixture_adapter(
        adapter_request,
        _scenario(
            adapter_request,
            suffix=suffix,
            body=_body(items),
            content_type="application/json; charset=utf-8",
        ),
    )


def _baseline(adapter_request, proposal) -> ObservationBaseline:
    parser = proposal.parser_result
    assert parser is not None
    return ObservationBaseline(
        source_definition_version_id=adapter_request.source_definition_version_id,
        validator_contract=adapter_request.validator_contract,
        source_body_digest=parser.source_body_digest,
        producer_slot_digest=parser.producer_slot_digest,
        representation_digest=parser.representation_digest,
        item_keys=parser.item_keys,
        validator=ConditionalValidator(etag='"fixture-etag"'),
        recorded_at=NOW,
    )


def _seed_source(system, model: ObservationModel) -> None:
    system.sources.register_definition(definition_request(), proof=proof())
    system.sources.record_definition_version(_model_version(model), proof=proof())


def _seed_check(
    system,
    adapter_request,
    *,
    suffix: int,
    trigger: TriggerRef | None = None,
):
    request, attempt = _check_records(adapter_request, suffix=suffix)
    if trigger is not None:
        request = replace(
            request,
            trigger=trigger,
            idempotency_key=f"model-check-request-{suffix}",
        )
    system.checks.register_request(request, proof=proof())
    system.checks.start_attempt(attempt, proof=proof())
    return request, attempt


def _admit(
    system,
    adapter_request,
    proposal,
    *,
    suffix: int,
    baseline_control: BaselineControl | None = None,
    transition_directives: tuple[TransitionDirective, ...] = (),
    trigger: TriggerRef | None = None,
):
    request, attempt = _seed_check(
        system,
        adapter_request,
        suffix=suffix,
        trigger=trigger,
    )
    admission = ProposalAdmissionRequest(
        check_request_id=request.request_id,
        check_attempt_id=attempt.attempt_id,
        adapter_request=adapter_request,
        proposal=proposal,
        baseline_control=baseline_control or BaselineControl(),
        transition_directives=transition_directives,
    )
    return system.checks.admit_proposal(admission, proof=proof()), admission


def _absence_guard(*, authorizing: bool) -> AbsenceEndingGuard:
    return AbsenceEndingGuard(
        complete_scope_digest=DIGEST_A,
        filter_contract_digest=DIGEST_B,
        pagination_contract_digest="sha256:" + "c" * 64,
        successful_complete_outcome=authorizing,
        identity_confirmed=True,
        scope_confirmed=True,
        pagination_complete=True,
        confirmation_count=2 if authorizing else 0,
        required_confirmations=2,
        grace_satisfied=True,
        no_alternative_explanation=True,
    )


def _agenda_guard() -> AgendaMissGuard:
    return AgendaMissGuard(
        expected_window_digest=DIGEST_A,
        confirmation_paths_digest=DIGEST_B,
        window_closed=True,
        grace_satisfied=True,
        confirmation_paths_checked=True,
        no_reschedule_or_cancellation=True,
        confirmation_outcomes_complete=True,
        source_failure_absent=True,
    )


def test_append_only_bounded_backfill_prevents_historical_flooding(tmp_path) -> None:
    system = open_check_system(tmp_path / "authority.sqlite3")
    _seed_source(system, ObservationModel.APPEND_ONLY)
    first_request = _adapter_request(ObservationModel.APPEND_ONLY, suffix=1)
    first_proposal = _proposal(
        first_request,
        suffix=1,
        items=[
            {
                "id": "old",
                "source_published_time": "2042-03-10T09:00:00.000000Z",
                "status": "published",
                "title": "Old history",
            },
            {
                "id": "recent",
                "source_published_time": "2042-03-12T09:30:00.000000Z",
                "status": "published",
                "title": "Recent history",
            },
        ],
    )
    first, _ = _admit(
        system,
        first_request,
        first_proposal,
        suffix=1,
    )

    assert first.baseline is not None
    assert first.baseline.request.disposition is BaselineDisposition.BOUNDED_BACKFILL
    entries = {
        entry.reason_code: entry.disposition
        for entry in first.baseline.request.entries
    }
    assert entries == {
        "OUTSIDE_BACKFILL_WINDOW": BaselineEntryDisposition.EXCLUDED,
        "WITHIN_BACKFILL_WINDOW": BaselineEntryDisposition.INCLUDED,
    }
    assert first.transitions == ()

    second_request = _adapter_request(
        ObservationModel.APPEND_ONLY,
        suffix=2,
        baseline=_baseline(first_request, first_proposal),
    )
    second_proposal = _proposal(
        second_request,
        suffix=2,
        items=[
            {
                "id": "old",
                "source_published_time": "2042-03-10T09:00:00.000000Z",
                "status": "published",
                "title": "Old history",
            },
            {
                "id": "recent",
                "source_published_time": "2042-03-12T09:30:00.000000Z",
                "status": "published",
                "title": "Recent history",
            },
            {
                "id": "new",
                "source_published_time": "2042-03-12T10:00:00.000000Z",
                "status": "published",
                "title": "New observation",
            },
        ],
    )
    second, _ = _admit(
        system,
        second_request,
        second_proposal,
        suffix=2,
    )

    assert [item.request.kind for item in second.transitions] == [
        ObservableTransitionKind.FIRST_OBSERVED
    ]
    system.close()


def test_rolling_disappearance_remains_ambiguous(tmp_path) -> None:
    system = open_check_system(tmp_path / "authority.sqlite3")
    _seed_source(system, ObservationModel.ROLLING_LIST)
    first_request = _adapter_request(ObservationModel.ROLLING_LIST, suffix=3)
    first_proposal = _proposal(
        first_request,
        suffix=3,
        items=[
            {
                "id": "rolling-1",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "active",
                "title": "Rolling item",
            }
        ],
    )
    first, _ = _admit(system, first_request, first_proposal, suffix=3)
    item_key = first_proposal.candidate_items[0].item_key

    second_request = _adapter_request(
        ObservationModel.ROLLING_LIST,
        suffix=4,
        baseline=_baseline(first_request, first_proposal),
    )
    second_proposal = _proposal(second_request, suffix=4, items=[])
    assert second_proposal.outcome is ObservationProposalOutcome.SUCCESS_EMPTY
    directive = TransitionDirective(
        item_key=item_key,
        kind=ObservableTransitionKind.AMBIGUOUS_ABSENCE,
        transition_discriminator="rolling-window-absence",
        absence_guard=_absence_guard(authorizing=False),
    )
    second, _ = _admit(
        system,
        second_request,
        second_proposal,
        suffix=4,
        transition_directives=(directive,),
    )

    assert first.transitions == ()
    assert second.transitions[0].request.kind is ObservableTransitionKind.AMBIGUOUS_ABSENCE
    assert second.transitions[0].request.current_revision_id is None
    system.close()


def test_complete_snapshot_can_end_only_with_complete_authorizing_guard(tmp_path) -> None:
    system = open_check_system(tmp_path / "authority.sqlite3")
    _seed_source(system, ObservationModel.COMPLETE_CURRENT_STATE)
    first_request = _adapter_request(
        ObservationModel.COMPLETE_CURRENT_STATE,
        suffix=5,
    )
    first_proposal = _proposal(
        first_request,
        suffix=5,
        items=[
            {
                "id": "active-1",
                "source_published_time": "2042-03-12T08:00:00.000000Z",
                "status": "active",
                "title": "First active item",
            },
            {
                "id": "active-2",
                "source_published_time": "2042-03-12T08:30:00.000000Z",
                "status": "active",
                "title": "Second active item",
            },
        ],
    )
    first, _ = _admit(system, first_request, first_proposal, suffix=5)
    assert first.baseline is not None
    assert first.baseline.request.disposition is BaselineDisposition.FIRST_OBSERVED_ACTIVE
    assert {item.request.kind for item in first.transitions} == {
        ObservableTransitionKind.ACTIVATED
    }
    missing_key = next(
        item.item_key
        for item in first_proposal.candidate_items
        if dict((field.name, field.value) for field in item.fields)["id"] == "active-2"
    )

    second_request = _adapter_request(
        ObservationModel.COMPLETE_CURRENT_STATE,
        suffix=6,
        baseline=_baseline(first_request, first_proposal),
    )
    second_proposal = _proposal(
        second_request,
        suffix=6,
        items=[
            {
                "id": "active-1",
                "source_published_time": "2042-03-12T08:00:00.000000Z",
                "status": "active",
                "title": "First active item",
            }
        ],
    )
    directive = TransitionDirective(
        item_key=missing_key,
        kind=ObservableTransitionKind.RESOLVED_OR_CLEARED,
        transition_discriminator="complete-snapshot-clearance",
        absence_guard=_absence_guard(authorizing=True),
    )
    second, _ = _admit(
        system,
        second_request,
        second_proposal,
        suffix=6,
        transition_directives=(directive,),
    )
    ending = second.transitions[0].request
    assert ending.kind is ObservableTransitionKind.RESOLVED_OR_CLEARED
    assert ending.basis is TransitionBasis.COMPLETE_SNAPSHOT_ABSENCE
    assert ending.current_revision_id is None

    partial_request = _adapter_request(
        ObservationModel.COMPLETE_CURRENT_STATE,
        suffix=7,
        baseline=_baseline(second_request, second_proposal),
    )
    duplicate = [
        {
            "id": "active-1",
            "source_published_time": "2042-03-12T08:00:00.000000Z",
            "status": "active",
            "title": "First active item",
        },
        {
            "id": "active-1",
            "source_published_time": "2042-03-12T08:00:00.000000Z",
            "status": "active",
            "title": "First active item",
        },
    ]
    partial_proposal = _proposal(partial_request, suffix=7, items=duplicate)
    assert partial_proposal.outcome is ObservationProposalOutcome.SUCCESS_PARTIAL
    with pytest.raises(ProposalAdmissionConflict, match="incomplete Outcome"):
        _admit(
            system,
            partial_request,
            partial_proposal,
            suffix=7,
            transition_directives=(directive,),
        )
    system.close()


def test_explicit_delta_requires_classification_and_replays_one_transition(tmp_path) -> None:
    system = open_check_system(tmp_path / "authority.sqlite3")
    _seed_source(system, ObservationModel.EXPLICIT_DELTA)
    first_request = _adapter_request(ObservationModel.EXPLICIT_DELTA, suffix=8)
    first_proposal = _proposal(
        first_request,
        suffix=8,
        items=[
            {
                "id": "delta-1",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "normal",
                "title": "Delta item",
            }
        ],
    )
    first, _ = _admit(system, first_request, first_proposal, suffix=8)
    assert first.transitions == ()

    second_request = _adapter_request(
        ObservationModel.EXPLICIT_DELTA,
        suffix=9,
        baseline=_baseline(first_request, first_proposal),
    )
    second_proposal = _proposal(
        second_request,
        suffix=9,
        items=[
            {
                "id": "delta-1",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "urgent",
                "title": "Delta item",
            }
        ],
    )
    request, attempt = _seed_check(system, second_request, suffix=9)
    unclassified = ProposalAdmissionRequest(
        request.request_id,
        attempt.attempt_id,
        second_request,
        second_proposal,
    )
    with pytest.raises(ProposalAdmissionConflict, match="transition directive"):
        system.checks.admit_proposal(unclassified, proof=proof())

    item_key = second_proposal.candidate_items[0].item_key
    directive = TransitionDirective(
        item_key=item_key,
        kind=ObservableTransitionKind.ESCALATED,
        transition_discriminator="explicit-urgency-escalation",
        change_facets=("STATUS",),
    )
    classified = replace(unclassified, transition_directives=(directive,))
    result = system.checks.admit_proposal(classified, proof=proof())
    replay = system.checks.admit_proposal(classified, proof=proof())

    assert result.transitions[0].request.kind is ObservableTransitionKind.ESCALATED
    assert result.transitions[0].request.basis is TransitionBasis.EXPLICIT_DELTA
    assert replay.transitions[0].event_id == result.transitions[0].event_id
    system.close()


def test_planned_agenda_baseline_reschedule_and_miss_remain_expectation_only(
    tmp_path,
) -> None:
    system = open_check_system(tmp_path / "authority.sqlite3")
    _seed_source(system, ObservationModel.PLANNED_AGENDA)
    first_request = _adapter_request(ObservationModel.PLANNED_AGENDA, suffix=10)
    first_proposal = _proposal(
        first_request,
        suffix=10,
        items=[
            {
                "expected_time": "2042-03-11T10:00:00.000000Z",
                "id": "past-agenda",
                "status": "planned",
                "title": "Past expectation",
            },
            {
                "expected_time": "2042-03-13T10:00:00.000000Z",
                "id": "future-agenda",
                "status": "planned",
                "title": "Future expectation",
            },
        ],
    )
    first, _ = _admit(system, first_request, first_proposal, suffix=10)
    assert first.baseline is not None
    assert first.baseline.request.disposition is BaselineDisposition.FUTURE_EXPECTATIONS_ONLY
    assert [item.request.kind for item in first.transitions] == [
        ObservableTransitionKind.AGENDA_CREATED
    ]
    future_key = next(
        item.item_key
        for item in first_proposal.candidate_items
        if dict((field.name, field.value) for field in item.fields)["id"]
        == "future-agenda"
    )

    second_request = _adapter_request(
        ObservationModel.PLANNED_AGENDA,
        suffix=11,
        baseline=_baseline(first_request, first_proposal),
    )
    second_proposal = _proposal(
        second_request,
        suffix=11,
        items=[
            {
                "expected_time": "2042-03-14T10:00:00.000000Z",
                "id": "future-agenda",
                "status": "planned",
                "title": "Future expectation",
            }
        ],
    )
    rescheduled = TransitionDirective(
        item_key=future_key,
        kind=ObservableTransitionKind.AGENDA_RESCHEDULED,
        transition_discriminator="agenda-rescheduled",
        change_facets=("EXPECTED_TIME",),
    )
    second, _ = _admit(
        system,
        second_request,
        second_proposal,
        suffix=11,
        transition_directives=(rescheduled,),
    )
    assert second.transitions[0].request.kind is ObservableTransitionKind.AGENDA_RESCHEDULED

    third_request = _adapter_request(
        ObservationModel.PLANNED_AGENDA,
        suffix=12,
        baseline=_baseline(second_request, second_proposal),
    )
    third_proposal = _proposal(third_request, suffix=12, items=[])
    missed = TransitionDirective(
        item_key=future_key,
        kind=ObservableTransitionKind.AGENDA_MISSED_EXPECTATION,
        transition_discriminator="agenda-missed-after-confirmation",
        agenda_guard=_agenda_guard(),
    )
    third, _ = _admit(
        system,
        third_request,
        third_proposal,
        suffix=12,
        transition_directives=(missed,),
    )
    assert third.transitions[0].request.kind is ObservableTransitionKind.AGENDA_MISSED_EXPECTATION
    assert third.transitions[0].request.current_revision_id is None
    system.close()


def test_empty_complete_snapshot_is_explicit_baseline_and_reset_replays(tmp_path) -> None:
    system = open_check_system(tmp_path / "authority.sqlite3")
    _seed_source(system, ObservationModel.COMPLETE_CURRENT_STATE)
    first_request = _adapter_request(
        ObservationModel.COMPLETE_CURRENT_STATE,
        suffix=13,
    )
    first_proposal = _proposal(first_request, suffix=13, items=[])
    first, _ = _admit(system, first_request, first_proposal, suffix=13)

    assert first.baseline is not None
    assert first.baseline.request.entries == ()
    assert first.transitions == ()

    reset_request = _adapter_request(
        ObservationModel.COMPLETE_CURRENT_STATE,
        suffix=14,
        baseline=_baseline(first_request, first_proposal),
    )
    reset_proposal = _proposal(reset_request, suffix=14, items=[])
    control = BaselineControl(
        action=BaselineAction.RESET,
        previous_decision_id=first.baseline.request.decision_id,
        reason_codes=("OPERATOR_RESET",),
    )
    trigger = TriggerRef(
        TriggerKind.RESET_REBUILD,
        "fixture-reset",
        "v1",
    )
    reset, admission = _admit(
        system,
        reset_request,
        reset_proposal,
        suffix=14,
        baseline_control=control,
        trigger=trigger,
    )
    replay = system.checks.admit_proposal(admission, proof=proof())

    assert reset.baseline is not None
    assert reset.baseline.request.kind is BaselineDecisionKind.RESET
    assert reset.baseline.request.previous_decision_id == first.baseline.request.decision_id
    assert replay.baseline is not None
    assert replay.baseline.event_id == reset.baseline.event_id
    system.close()


def test_partial_snapshot_can_advance_independently_valid_current_item(tmp_path) -> None:
    system = open_check_system(tmp_path / "authority.sqlite3")
    _seed_source(system, ObservationModel.COMPLETE_CURRENT_STATE)
    first_request = _adapter_request(
        ObservationModel.COMPLETE_CURRENT_STATE,
        suffix=20,
    )
    first_proposal = _proposal(
        first_request,
        suffix=20,
        items=[
            {
                "id": "partial-1",
                "source_published_time": "2042-03-12T08:00:00.000000Z",
                "status": "active",
                "title": "Initial state",
            }
        ],
    )
    first, _ = _admit(system, first_request, first_proposal, suffix=20)
    assert first.baseline is not None

    second_request = _adapter_request(
        ObservationModel.COMPLETE_CURRENT_STATE,
        suffix=21,
        baseline=_baseline(first_request, first_proposal),
    )
    changed = {
        "id": "partial-1",
        "source_published_time": "2042-03-12T08:00:00.000000Z",
        "status": "updated",
        "title": "Updated state",
    }
    second_proposal = _proposal(
        second_request,
        suffix=21,
        items=[changed, changed],
    )
    assert second_proposal.outcome is ObservationProposalOutcome.SUCCESS_PARTIAL

    second, _ = _admit(system, second_request, second_proposal, suffix=21)

    assert len(second.observations) == 1
    assert [item.request.kind for item in second.transitions] == [
        ObservableTransitionKind.REVISED
    ]
    assert second.transitions[0].request.current_revision_id is not None
    assert len(second.findings) == 1
    system.close()


def test_one_outcome_cannot_be_reclassified_for_the_same_item(tmp_path) -> None:
    system = open_check_system(tmp_path / "authority.sqlite3")
    _seed_source(system, ObservationModel.EXPLICIT_DELTA)
    first_request = _adapter_request(ObservationModel.EXPLICIT_DELTA, suffix=22)
    first_proposal = _proposal(
        first_request,
        suffix=22,
        items=[
            {
                "id": "classified-1",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "normal",
                "title": "Classified delta",
            }
        ],
    )
    _admit(system, first_request, first_proposal, suffix=22)

    second_request = _adapter_request(
        ObservationModel.EXPLICIT_DELTA,
        suffix=23,
        baseline=_baseline(first_request, first_proposal),
    )
    second_proposal = _proposal(
        second_request,
        suffix=23,
        items=[
            {
                "id": "classified-1",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "urgent",
                "title": "Classified delta",
            }
        ],
    )
    request, attempt = _seed_check(system, second_request, suffix=23)
    item_key = second_proposal.candidate_items[0].item_key
    base = ProposalAdmissionRequest(
        request.request_id,
        attempt.attempt_id,
        second_request,
        second_proposal,
    )
    escalated = replace(
        base,
        transition_directives=(
            TransitionDirective(
                item_key=item_key,
                kind=ObservableTransitionKind.ESCALATED,
                transition_discriminator="classified-escalation",
                change_facets=("STATUS",),
            ),
        ),
    )
    system.checks.admit_proposal(escalated, proof=proof())

    reclassified = replace(
        base,
        transition_directives=(
            TransitionDirective(
                item_key=item_key,
                kind=ObservableTransitionKind.DEESCALATED,
                transition_discriminator="conflicting-deescalation",
                change_facets=("STATUS",),
            ),
        ),
    )
    with pytest.raises(ProposalAdmissionConflict, match="conflicted"):
        system.checks.admit_proposal(reclassified, proof=proof())
    system.close()


def test_one_outcome_cannot_reclassify_its_baseline_decision(tmp_path) -> None:
    system = open_check_system(tmp_path / "authority.sqlite3")
    _seed_source(system, ObservationModel.COMPLETE_CURRENT_STATE)
    adapter_request = _adapter_request(
        ObservationModel.COMPLETE_CURRENT_STATE,
        suffix=24,
    )
    proposal = _proposal(adapter_request, suffix=24, items=[])
    first, admission = _admit(
        system,
        adapter_request,
        proposal,
        suffix=24,
    )
    assert first.baseline is not None

    reclassified = replace(
        admission,
        baseline_control=BaselineControl(
            action=BaselineAction.MANUAL_HOLD,
            reason_codes=("LATE_RECLASSIFICATION",),
        ),
    )
    with pytest.raises(ProposalAdmissionConflict, match="classification differs"):
        system.checks.admit_proposal(reclassified, proof=proof())
    system.close()
