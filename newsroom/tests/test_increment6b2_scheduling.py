from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from newsroom.increment6.outcomes import (
    PriorityLane,
    PrioritySelection,
    ReasonReference,
)
from newsroom.increment6.scheduling import (
    RESERVED_CAPACITY_POLICY,
    STARVATION_OBSERVATION,
    URGENCY_DEADLINE_POLICY,
    CapacityAllocationDisposition,
    CapacityClass,
    CapacityPathState,
    CapacityPopulationItem,
    CapacityRevalidationEvidence,
    CapacityRevalidationResult,
    CapacitySnapshot,
    CapacityWorkState,
    DeadlineBoundary,
    DeadlineKind,
    LaneTimingRule,
    ReservedCapacityDecision,
    ReservedCapacityDisposition,
    SchedulingContractError,
    SchedulingEligibility,
    StarvationState,
    UrgencyDeadlineDecision,
    UrgencyDeadlineInput,
    allocate_reserved_capacity,
    calculate_urgency_deadline,
    capacity_class_for_lane,
)

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64


def _deadline(
    due_at: str = "2026-08-09T15:30:00Z",
) -> DeadlineBoundary:
    due = datetime.strptime(due_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    local = due.astimezone(ZoneInfo("Europe/London"))
    offset = local.utcoffset()
    assert offset is not None
    return DeadlineBoundary(
        kind=DeadlineKind.HARD_ACTION,
        due_at=due_at,
        source_time_zone="Europe/London",
        source_local_time=local.strftime("%Y-%m-%dT%H:%M:%S"),
        source_utc_offset_minutes=int(offset.total_seconds() // 60),
        source_fold=local.fold,
    )


def _rules() -> tuple[LaneTimingRule, ...]:
    values = {
        PriorityLane.CONTAINMENT: (60, 120, True),
        PriorityLane.URGENT: (120, 300, True),
        PriorityLane.TIME_SENSITIVE: (900, 1_800, True),
        PriorityLane.PLANNED_WINDOW: (1_800, 3_600, True),
        PriorityLane.ROUTINE: (3_600, 7_200, False),
        PriorityLane.OPTIONAL_EVALUATION: (7_200, 14_400, False),
    }
    return tuple(
        LaneTimingRule(
            lane=lane,
            starvation_warning_seconds=values[lane][0],
            starvation_limit_seconds=values[lane][1],
            explicit_deadline_required=values[lane][2],
        )
        for lane in PriorityLane
    )


def _policy() -> URGENCY_DEADLINE_POLICY:
    return URGENCY_DEADLINE_POLICY(
        policy_id="fixture-scheduling-policy",
        policy_version="v1",
        clock_time_zone="UTC",
        tie_break="WORK_ITEM_VERSION_ID_ASC",
        lane_rules=_rules(),
    )


def _input(
    *,
    work_item_id: str = "work-item-a",
    version_id: str = "work-item-version-a",
    version_digest: str = SHA_A,
    lane: PriorityLane = PriorityLane.TIME_SENSITIVE,
    enqueued_at: str = "2026-08-09T15:00:00Z",
    observed_at: str = "2026-08-09T15:10:00Z",
    deadline: DeadlineBoundary | None = None,
    eligibility: SchedulingEligibility = SchedulingEligibility.CURRENT_ELIGIBLE,
    delay_consequence_ordinal: int = 2,
    staleness_risk_ordinal: int = 1,
    dependency_ready: bool = True,
) -> UrgencyDeadlineInput:
    if deadline is None and lane in {
        PriorityLane.CONTAINMENT,
        PriorityLane.URGENT,
        PriorityLane.TIME_SENSITIVE,
        PriorityLane.PLANNED_WINDOW,
    }:
        deadline = _deadline()
    return UrgencyDeadlineInput(
        work_item_id=work_item_id,
        work_item_version_id=version_id,
        work_item_version_digest=version_digest,
        priority_selection=PrioritySelection(
            work_identity=work_item_id,
            work_version=version_id,
            lane=lane,
            basis_references=(
                ReasonReference(
                    reference_type="lead-disposition",
                    identifier="decision-a",
                    digest=SHA_B,
                ),
            ),
        ),
        lane=lane,
        enqueued_at=enqueued_at,
        observed_at=observed_at,
        deadline=deadline,
        eligibility=eligibility,
        delay_consequence_ordinal=delay_consequence_ordinal,
        staleness_risk_ordinal=staleness_risk_ordinal,
        dependency_ready=dependency_ready,
    )


def test_identical_inputs_produce_byte_identical_deadline_and_order() -> None:
    policy = _policy()
    item = _input()

    first = calculate_urgency_deadline(policy=policy, item=item)
    second = calculate_urgency_deadline(policy=policy, item=item)

    assert first.canonical_bytes == second.canonical_bytes
    assert first.decision_digest == second.decision_digest
    assert first.order_key == second.order_key
    assert first.effective_deadline == "2026-08-09T15:30:00Z"
    assert first.queue_age_seconds == 600
    assert first.deadline_overdue is False
    assert first.schedulable is True
    assert first.authority == "NONE"
    assert first.effect == "NONE"
    assert first.production_activation_authorised is False
    assert UrgencyDeadlineDecision.from_canonical_bytes(first.canonical_bytes) == first


def _input_with_basis_reference_count(count: int) -> UrgencyDeadlineInput:
    item = _input()
    references = tuple(
        ReasonReference(
            reference_type="boundary-basis",
            identifier=f"{index:03d}-" + "x" * 3_996,
            digest=SHA_B,
        )
        for index in range(count)
    )
    return replace(
        item,
        priority_selection=replace(
            item.priority_selection,
            basis_references=references,
        ),
    )


def test_standalone_observation_size_boundary_matches_canonical_parser() -> None:
    accepted = calculate_urgency_deadline(
        policy=_policy(),
        item=_input_with_basis_reference_count(220),
    )

    assert len(accepted.canonical_bytes) < 917_504
    assert (
        UrgencyDeadlineDecision.from_canonical_bytes(accepted.canonical_bytes)
        == accepted
    )
    with pytest.raises(SchedulingContractError):
        calculate_urgency_deadline(
            policy=_policy(),
            item=_input_with_basis_reference_count(230),
        )


def test_deadline_boundary_resolves_exact_time_zone_and_dst_fold() -> None:
    first_fold = DeadlineBoundary(
        kind=DeadlineKind.PLANNED_WINDOW_END,
        due_at="2026-10-25T00:30:00Z",
        source_time_zone="Europe/London",
        source_local_time="2026-10-25T01:30:00",
        source_utc_offset_minutes=60,
        source_fold=0,
    )
    second_fold = replace(
        first_fold,
        due_at="2026-10-25T01:30:00Z",
        source_utc_offset_minutes=0,
        source_fold=1,
    )

    assert first_fold.due_at != second_fold.due_at
    with pytest.raises(SchedulingContractError):
        replace(first_fold, source_fold=1)
    with pytest.raises(SchedulingContractError):
        DeadlineBoundary(
            kind=DeadlineKind.HARD_ACTION,
            due_at="2026-03-29T01:30:00Z",
            source_time_zone="Europe/London",
            source_local_time="2026-03-29T01:30:00",
            source_utc_offset_minutes=0,
            source_fold=0,
        )


@pytest.mark.parametrize(
    "source_time_zone",
    ("Etc/../../etc/passwd", "UTC/", "A//B"),
)
def test_non_normalised_time_zone_fails_closed_at_constructor_and_parser(
    source_time_zone: str,
) -> None:
    with pytest.raises(SchedulingContractError):
        replace(_deadline(), source_time_zone=source_time_zone)

    observation = calculate_urgency_deadline(policy=_policy(), item=_input())
    value = observation.canonical_value()
    value["input"]["deadline"]["source_time_zone"] = source_time_zone  # type: ignore[index]
    raw = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    with pytest.raises(SchedulingContractError):
        UrgencyDeadlineDecision.from_canonical_bytes(raw)


def test_required_lane_cannot_drop_its_deadline() -> None:
    tampered = replace(_input(), deadline=None)

    with pytest.raises(SchedulingContractError):
        calculate_urgency_deadline(policy=_policy(), item=tampered)


def test_lane_cannot_be_rebound_away_from_exact_priority_selection() -> None:
    item = _input(lane=PriorityLane.ROUTINE, deadline=None)
    with pytest.raises(SchedulingContractError):
        replace(item, lane=PriorityLane.URGENT, deadline=_deadline())


def test_stale_or_blocked_work_never_becomes_schedulable_by_priority() -> None:
    for state in (
        SchedulingEligibility.STALE,
        SchedulingEligibility.CLOSED,
        SchedulingEligibility.POLICY_BLOCKED,
        SchedulingEligibility.CURRENT_DEPENDENCY_BLOCKED,
    ):
        decision = calculate_urgency_deadline(
            policy=_policy(),
            item=_input(eligibility=state),
        )
        assert decision.schedulable is False
        assert decision.order_key is None
        assert decision.revalidation_required is (state is SchedulingEligibility.STALE)


def test_starvation_is_measurable_and_requires_current_revalidation() -> None:
    warning = calculate_urgency_deadline(
        policy=_policy(),
        item=_input(
            lane=PriorityLane.ROUTINE,
            enqueued_at="2026-08-09T13:30:00Z",
            observed_at="2026-08-09T15:00:00Z",
            deadline=None,
        ),
    )
    starved = calculate_urgency_deadline(
        policy=_policy(),
        item=_input(
            lane=PriorityLane.ROUTINE,
            enqueued_at="2026-08-09T12:00:00Z",
            observed_at="2026-08-09T15:00:00Z",
            deadline=None,
        ),
    )

    assert warning.starvation_state is StarvationState.AT_RISK
    assert warning.revalidation_required is False
    assert starved.starvation_state is StarvationState.STARVED
    assert starved.revalidation_required is True
    assert starved.starvation_overrun_seconds == 3_600
    assert (
        STARVATION_OBSERVATION.from_canonical_bytes(starved.canonical_bytes) == starved
    )


def test_overdue_exact_deadline_is_visible_and_requires_revalidation() -> None:
    decision = calculate_urgency_deadline(
        policy=_policy(),
        item=_input(
            observed_at="2026-08-09T15:40:00Z",
            deadline=_deadline("2026-08-09T15:30:00Z"),
        ),
    )

    assert decision.deadline_overdue is True
    assert decision.revalidation_required is True


def test_within_lane_order_is_deadline_then_consequence_risk_age_and_tie_break() -> (
    None
):
    policy = _policy()
    early = calculate_urgency_deadline(
        policy=policy,
        item=_input(
            version_id="work-item-version-z",
            deadline=_deadline("2026-08-09T15:20:00Z"),
            delay_consequence_ordinal=0,
            staleness_risk_ordinal=0,
        ),
    )
    later_high_risk = calculate_urgency_deadline(
        policy=policy,
        item=_input(
            version_id="work-item-version-a",
            deadline=_deadline("2026-08-09T15:30:00Z"),
            delay_consequence_ordinal=3,
            staleness_risk_ordinal=3,
        ),
    )
    same_a = calculate_urgency_deadline(
        policy=policy,
        item=_input(version_id="work-item-version-a"),
    )
    same_b = calculate_urgency_deadline(
        policy=policy,
        item=_input(version_id="work-item-version-b"),
    )

    assert early.order_key < later_high_risk.order_key
    assert same_a.order_key < same_b.order_key


def _capacity_policy() -> RESERVED_CAPACITY_POLICY:
    return RESERVED_CAPACITY_POLICY(
        policy_id="fixture-capacity-policy",
        policy_version="v1",
        total_slots=6,
        urgent_reserved_slots=2,
        minimum_ordinary_slots=2,
        degraded_urgent_disposition=(
            ReservedCapacityDisposition.URGENT_VISIBLE_OPERATIONAL_HOLD
        ),
    )


def _capacity_item(
    name: str,
    *,
    lane: PriorityLane,
    state: CapacityWorkState = CapacityWorkState.PENDING,
    starved: bool = False,
    revalidated: bool = False,
    revalidation_result: CapacityRevalidationResult | None = None,
    identity: str | None = None,
) -> CapacityPopulationItem:
    digest = (
        "sha256:" + (name[-1].encode().hex()[0] if name[-1].isalnum() else "d") * 64
    )
    enqueued_at = (
        "2026-08-09T12:00:00Z"
        if starved
        else "2026-08-09T15:09:30Z"
        if lane in {PriorityLane.CONTAINMENT, PriorityLane.URGENT}
        else "2026-08-09T15:05:00Z"
    )
    observation = calculate_urgency_deadline(
        policy=_policy(),
        item=_input(
            work_item_id=identity or f"work-item-{name}",
            version_id=f"work-item-version-{name}",
            version_digest=digest,
            lane=lane,
            enqueued_at=enqueued_at,
            observed_at="2026-08-09T15:10:00Z",
            deadline=None
            if lane in {PriorityLane.ROUTINE, PriorityLane.OPTIONAL_EVALUATION}
            else _deadline(),
        ),
    )
    evidence = None
    if observation.revalidation_required:
        result = (
            revalidation_result or CapacityRevalidationResult.REVALIDATED
            if revalidated
            else revalidation_result or CapacityRevalidationResult.EXPIRED
        )
        evidence = CapacityRevalidationEvidence(
            work_item_id=observation.item.work_item_id,
            work_item_version_id=observation.item.work_item_version_id,
            work_item_version_digest=observation.item.work_item_version_digest,
            starvation_observation_digest=observation.decision_digest,
            governing_policy_digest=observation.policy.policy_digest,
            snapshot_observed_at=observation.item.observed_at,
            currentness_basis=(
                ReasonReference(
                    reference_type=f"revalidation-{result.value.lower()}",
                    identifier=f"receipt-{name}",
                    digest=SHA_C,
                ),
            ),
            result=result,
        )
    return CapacityPopulationItem(
        observation=observation,
        state=state,
        revalidation_evidence=evidence,
    )


def _snapshot(
    *items: CapacityPopulationItem,
    urgent_path_state: CapacityPathState = CapacityPathState.AVAILABLE,
) -> CapacitySnapshot:
    return CapacitySnapshot(
        observed_at="2026-08-09T15:10:00Z",
        urgency_policy=_policy(),
        population=tuple(sorted(items, key=lambda item: item.identity_key)),
        urgent_path_state=urgent_path_state,
    )


def test_capacity_population_derives_counts_and_exact_grants_from_canonical_lanes() -> (
    None
):
    items = tuple(
        _capacity_item(str(index), lane=lane, state=state)
        for index, (lane, state) in enumerate(
            (
                (PriorityLane.URGENT, CapacityWorkState.ACTIVE),
                (PriorityLane.TIME_SENSITIVE, CapacityWorkState.ACTIVE),
                (PriorityLane.CONTAINMENT, CapacityWorkState.PENDING),
                (PriorityLane.URGENT, CapacityWorkState.PENDING),
                (PriorityLane.PLANNED_WINDOW, CapacityWorkState.PENDING),
                (PriorityLane.ROUTINE, CapacityWorkState.PENDING),
            )
        )
    )
    snapshot = _snapshot(*items)
    decision = allocate_reserved_capacity(policy=_capacity_policy(), snapshot=snapshot)

    assert (snapshot.active_urgent_slots, snapshot.active_ordinary_slots) == (1, 1)
    assert (snapshot.pending_urgent, snapshot.pending_ordinary) == (2, 2)
    assert decision.urgent_grants == 2
    assert decision.ordinary_grants == 2
    assert {
        (item.work_item_id, item.work_item_version_digest)
        for item in decision.granted_items
    } == {(item.work_item_id, item.work_item_version_digest) for item in items[2:]}
    assert (
        ReservedCapacityDecision.from_canonical_bytes(decision.canonical_bytes)
        == decision
    )


def test_capacity_classes_are_closed_over_canonical_lanes() -> None:
    assert (
        capacity_class_for_lane(PriorityLane.CONTAINMENT)
        is CapacityClass.URGENT_RESERVED
    )
    assert capacity_class_for_lane(PriorityLane.URGENT) is CapacityClass.URGENT_RESERVED
    for lane in (
        PriorityLane.TIME_SENSITIVE,
        PriorityLane.PLANNED_WINDOW,
        PriorityLane.ROUTINE,
        PriorityLane.OPTIONAL_EVALUATION,
    ):
        assert capacity_class_for_lane(lane) is CapacityClass.ORDINARY


def test_duplicate_identity_version_or_conflicting_version_fails_closed() -> None:
    item = _capacity_item("duplicate", lane=PriorityLane.ROUTINE)
    with pytest.raises(SchedulingContractError):
        _snapshot(item, item)
    conflicting = _capacity_item(
        "other", lane=PriorityLane.ROUTINE, identity=item.work_item_id
    )
    with pytest.raises(SchedulingContractError):
        _snapshot(item, conflicting)


def test_caller_cannot_tamper_with_derived_counts_lane_or_digest() -> None:
    item = _capacity_item("tamper", lane=PriorityLane.URGENT)
    decision = allocate_reserved_capacity(
        policy=_capacity_policy(), snapshot=_snapshot(item)
    )
    value = json.loads(decision.canonical_bytes)
    value["snapshot"]["pending_urgent"] = 99
    with pytest.raises(SchedulingContractError):
        ReservedCapacityDecision.from_canonical_bytes(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        )
    value = json.loads(decision.canonical_bytes)
    value["snapshot"]["population"][0]["lane"] = PriorityLane.ROUTINE.value
    with pytest.raises(SchedulingContractError):
        ReservedCapacityDecision.from_canonical_bytes(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        )


def test_capacity_snapshot_rejects_mixed_exact_urgency_policy_thresholds() -> None:
    base = _capacity_item("base-policy", lane=PriorityLane.ROUTINE)
    changed_rules = list(_rules())
    changed_rules[PriorityLane.ROUTINE.ordinal - 1] = replace(
        changed_rules[PriorityLane.ROUTINE.ordinal - 1],
        starvation_warning_seconds=3_601,
        starvation_limit_seconds=7_201,
    )
    changed_policy = replace(_policy(), lane_rules=tuple(changed_rules))
    changed_observation = calculate_urgency_deadline(
        policy=changed_policy,
        item=_input(
            work_item_id="work-item-changed-policy",
            version_id="work-item-version-changed-policy",
            version_digest=SHA_C,
            lane=PriorityLane.ROUTINE,
            enqueued_at="2026-08-09T15:05:00Z",
            observed_at="2026-08-09T15:10:00Z",
            deadline=None,
        ),
    )
    changed = CapacityPopulationItem(
        observation=changed_observation,
        state=CapacityWorkState.PENDING,
        revalidation_evidence=None,
    )

    with pytest.raises(SchedulingContractError):
        _snapshot(base, changed)


def test_revalidation_evidence_rejects_caller_flip_replay_and_binding_drift() -> None:
    expired = _capacity_item("receipt", lane=PriorityLane.ROUTINE, starved=True)
    evidence = expired.revalidation_evidence
    assert evidence is not None

    with pytest.raises(SchedulingContractError):
        replace(evidence, result=CapacityRevalidationResult.REVALIDATED)
    for drift in (
        {"snapshot_observed_at": "2026-08-09T15:11:00Z"},
        {"governing_policy_digest": SHA_A},
        {"starvation_observation_digest": SHA_B},
        {"work_item_version_digest": SHA_C},
    ):
        with pytest.raises(SchedulingContractError):
            replace(expired, revalidation_evidence=replace(evidence, **drift))

    decision = allocate_reserved_capacity(
        policy=_capacity_policy(), snapshot=_snapshot(expired)
    )
    tampered = json.loads(decision.canonical_bytes)
    raw_evidence = tampered["snapshot"]["population"][0]["revalidation_evidence"]
    raw_evidence["result"] = CapacityRevalidationResult.REVALIDATED.value
    with pytest.raises(SchedulingContractError):
        ReservedCapacityDecision.from_canonical_bytes(
            json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode()
        )


def test_revalidated_starved_routine_gets_next_ordinary_grant_before_fresh_inflow() -> (
    None
):
    active = tuple(
        _capacity_item(
            f"active-{index}",
            lane=PriorityLane.TIME_SENSITIVE,
            state=CapacityWorkState.ACTIVE,
        )
        for index in range(3)
    )
    fresh = _capacity_item("fresh", lane=PriorityLane.TIME_SENSITIVE)
    protected = _capacity_item(
        "protected", lane=PriorityLane.ROUTINE, starved=True, revalidated=True
    )
    decision = allocate_reserved_capacity(
        policy=_capacity_policy(), snapshot=_snapshot(*active, fresh, protected)
    )

    assert decision.ordinary_grants == 1
    assert decision.granted_items == (protected,)
    protected_allocation = next(a for a in decision.allocations if a.item == protected)
    fresh_allocation = next(a for a in decision.allocations if a.item == fresh)
    assert protected_allocation.protected_routine_grant is True
    assert protected_allocation.disposition is CapacityAllocationDisposition.GRANTED
    assert (
        fresh_allocation.disposition is CapacityAllocationDisposition.CAPACITY_DEFERRED
    )


def test_starved_routine_requires_visible_revalidation_before_protection() -> None:
    fresh = _capacity_item("fresh2", lane=PriorityLane.TIME_SENSITIVE)
    awaiting = _capacity_item("awaiting", lane=PriorityLane.ROUTINE, starved=True)
    decision = allocate_reserved_capacity(
        policy=_capacity_policy(), snapshot=_snapshot(fresh, awaiting)
    )

    assert decision.granted_items == (fresh,)
    allocation = next(a for a in decision.allocations if a.item == awaiting)
    assert allocation.disposition is CapacityAllocationDisposition.CAPACITY_DEFERRED
    assert allocation.item.revalidation_result is CapacityRevalidationResult.EXPIRED
    assert allocation.protected_routine_grant is False


def test_degraded_urgent_is_exact_visible_hold_and_never_downgraded() -> None:
    urgent = _capacity_item("urgent", lane=PriorityLane.URGENT)
    ordinary = _capacity_item("ordinary", lane=PriorityLane.ROUTINE)
    decision = allocate_reserved_capacity(
        policy=_capacity_policy(),
        snapshot=_snapshot(
            urgent, ordinary, urgent_path_state=CapacityPathState.DEGRADED
        ),
    )

    assert decision.urgent_grants == 0
    assert decision.ordinary_grants == 1
    assert (
        decision.urgent_disposition
        is ReservedCapacityDisposition.URGENT_VISIBLE_OPERATIONAL_HOLD
    )
    assert (
        next(a for a in decision.allocations if a.item == urgent).disposition
        is CapacityAllocationDisposition.URGENT_VISIBLE_OPERATIONAL_HOLD
    )
    assert decision.downgraded_urgent_to_ordinary is False


def test_degraded_urgent_hold_remains_primary_during_expired_revalidation() -> None:
    urgent = _capacity_item("urgent-expired", lane=PriorityLane.URGENT, starved=True)
    decision = allocate_reserved_capacity(
        policy=_capacity_policy(),
        snapshot=_snapshot(urgent, urgent_path_state=CapacityPathState.DEGRADED),
    )
    allocation = decision.allocations[0]

    assert allocation.disposition is (
        CapacityAllocationDisposition.URGENT_VISIBLE_OPERATIONAL_HOLD
    )
    assert allocation.item.revalidation_result is CapacityRevalidationResult.EXPIRED
    assert decision.urgent_grants == 0
    assert decision.downgraded_urgent_to_ordinary is False


def test_maximum_valid_population_decision_round_trips_canonically() -> None:
    items = tuple(
        _capacity_item(f"maximum-{index:02d}", lane=PriorityLane.TIME_SENSITIVE)
        for index in range(48)
    )
    decision = allocate_reserved_capacity(
        policy=_capacity_policy(), snapshot=_snapshot(*items)
    )

    assert len(decision.snapshot.population) == 48
    assert (
        ReservedCapacityDecision.from_canonical_bytes(decision.canonical_bytes)
        == decision
    )


@pytest.mark.parametrize("active_urgent", range(5))
@pytest.mark.parametrize("active_ordinary", range(5))
def test_capacity_invariants_hold_across_bounded_population_grid(
    active_urgent: int, active_ordinary: int
) -> None:
    if active_urgent > 4 or active_ordinary > 4 or active_urgent + active_ordinary > 6:
        return
    items = [
        *(
            _capacity_item(
                f"au-{index}", lane=PriorityLane.URGENT, state=CapacityWorkState.ACTIVE
            )
            for index in range(active_urgent)
        ),
        *(
            _capacity_item(
                f"ao-{index}", lane=PriorityLane.ROUTINE, state=CapacityWorkState.ACTIVE
            )
            for index in range(active_ordinary)
        ),
        *(
            _capacity_item(f"pu-{index}", lane=PriorityLane.URGENT)
            for index in range(8)
        ),
        *(
            _capacity_item(f"po-{index}", lane=PriorityLane.TIME_SENSITIVE)
            for index in range(8)
        ),
    ]
    if active_urgent > 4 or active_ordinary > 4:
        with pytest.raises(SchedulingContractError):
            allocate_reserved_capacity(
                policy=_capacity_policy(), snapshot=_snapshot(*items)
            )
        return
    decision = allocate_reserved_capacity(
        policy=_capacity_policy(), snapshot=_snapshot(*items)
    )
    assert decision.active_after_urgent <= decision.policy.max_urgent_slots
    assert decision.active_after_ordinary <= decision.policy.ordinary_capacity_ceiling
    assert (
        len(decision.granted_items) + active_urgent + active_ordinary
        <= decision.policy.total_slots
    )
    assert len({item.identity_key for item in decision.granted_items}) == len(
        decision.granted_items
    )


def test_capacity_policy_rejects_configuration_that_lets_urgent_take_every_slot() -> (
    None
):
    with pytest.raises(SchedulingContractError):
        replace(_capacity_policy(), minimum_ordinary_slots=0)
    with pytest.raises(SchedulingContractError):
        replace(_capacity_policy(), urgent_reserved_slots=6)


def test_decision_parsers_reject_unknown_duplicate_and_noncanonical_json() -> None:
    decision = calculate_urgency_deadline(policy=_policy(), item=_input())
    value = json.loads(decision.canonical_bytes)
    value["unexpected"] = True
    with pytest.raises(SchedulingContractError):
        UrgencyDeadlineDecision.from_canonical_bytes(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        )

    duplicate = decision.canonical_bytes.replace(
        b'{"authority":', b'{"authority":"NONE","authority":', 1
    )
    with pytest.raises(SchedulingContractError):
        UrgencyDeadlineDecision.from_canonical_bytes(duplicate)

    with pytest.raises(SchedulingContractError):
        UrgencyDeadlineDecision.from_canonical_bytes(
            json.dumps(json.loads(decision.canonical_bytes), indent=2).encode()
        )

    wrong_boolean_type = json.loads(decision.canonical_bytes)
    wrong_boolean_type["deadline_overdue"] = 0
    with pytest.raises(SchedulingContractError):
        UrgencyDeadlineDecision.from_canonical_bytes(
            json.dumps(
                wrong_boolean_type,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )

    capacity = allocate_reserved_capacity(
        policy=_capacity_policy(),
        snapshot=_snapshot(),
    )
    wrong_integer_type = json.loads(capacity.canonical_bytes)
    wrong_integer_type["urgent_grants"] = True
    with pytest.raises(SchedulingContractError):
        ReservedCapacityDecision.from_canonical_bytes(
            json.dumps(
                wrong_integer_type,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )


def test_total_contract_boundaries_never_leak_raw_numeric_or_datetime_errors() -> None:
    with pytest.raises(SchedulingContractError):
        calculate_urgency_deadline(
            policy=_policy(),
            item=_input(
                lane=PriorityLane.ROUTINE,
                enqueued_at="9999-12-31T23:59:00Z",
                observed_at="9999-12-31T23:59:30Z",
                deadline=None,
            ),
        )
    with pytest.raises(SchedulingContractError):
        replace(_rules()[-1], starvation_limit_seconds=315_576_001)

    decision = calculate_urgency_deadline(policy=_policy(), item=_input())
    huge_integer = decision.canonical_bytes.replace(
        b'"queue_age_seconds":600',
        b'"queue_age_seconds":' + b"9" * 5_000,
    )
    with pytest.raises(SchedulingContractError):
        UrgencyDeadlineDecision.from_canonical_bytes(huge_integer)
    with pytest.raises(SchedulingContractError):
        UrgencyDeadlineDecision.from_canonical_bytes(b"{" + b" " * 1_000_000)


def test_canonical_parsers_reject_boolean_ordinals_as_type_confusion() -> None:
    decision = calculate_urgency_deadline(policy=_policy(), item=_input())
    value = json.loads(decision.canonical_bytes)
    value["input"]["lane_ordinal"] = True
    with pytest.raises(SchedulingContractError):
        UrgencyDeadlineDecision.from_canonical_bytes(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        )

    value = json.loads(decision.canonical_bytes)
    value["policy"]["lane_rules"][0]["lane_ordinal"] = True
    with pytest.raises(SchedulingContractError):
        UrgencyDeadlineDecision.from_canonical_bytes(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        )


def test_deep_json_and_canonical_recursion_fail_as_contract_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deeply_nested = b'{"value":' * 1_100 + b"0" + b"}" * 1_100
    with pytest.raises(SchedulingContractError):
        ReservedCapacityDecision.from_canonical_bytes(deeply_nested)

    decision = calculate_urgency_deadline(policy=_policy(), item=_input())
    raw = decision.canonical_bytes

    def recursive_canonical(_: object) -> bytes:
        raise RecursionError("fixture canonical recursion")

    monkeypatch.setattr(
        "newsroom.increment6.scheduling.canonical_json_bytes",
        recursive_canonical,
    )
    with pytest.raises(SchedulingContractError):
        UrgencyDeadlineDecision.from_canonical_bytes(raw)


def test_interface_aliases_and_schema_boundary_are_exact() -> None:
    assert URGENCY_DEADLINE_POLICY.__name__ == "UrgencyDeadlinePolicy"
    assert RESERVED_CAPACITY_POLICY.__name__ == "ReservedCapacityPolicy"
    assert STARVATION_OBSERVATION.__name__ == "StarvationObservation"
    assert _policy().schema_version == (
        "newsroom.increment6.triage-scheduling-policy.v1"
    )
    assert _capacity_policy().schema_version == (
        "newsroom.increment6.triage-scheduling-policy.v1"
    )
    assert SHA_C != _policy().policy_digest
