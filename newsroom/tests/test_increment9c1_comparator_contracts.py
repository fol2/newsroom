from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment9.comparator import (
    EXPECTED_COMPARATOR_ARMS,
    EXPECTED_COMPARATOR_PHASE_IDS,
    EXPECTED_FAULT_BEHAVIOUR,
    EXPECTED_FAULT_INVENTORY,
    EXPECTED_PHASE_ORDER,
    EXPECTED_STOP_PRECEDENCE,
    ZERO_TOLERANCE_OBSERVATIONS,
    AdmissionDisposition,
    ApprovedPhaseAdmissionController,
    BudgetCaps,
    ComparatorContractError,
    ComparatorPlan,
    ExposureContract,
    FaultCampaignManifest,
    FaultKind,
    PhaseAdmissionRequest,
    ResourceReservation,
    StopObservation,
    StopReason,
    build_fault_campaign_manifest,
    resolve_stop_reason,
)
from newsroom.increment9.epoch import (
    EFFECTIVE_MANIFEST_IDENTITY_KEYS,
    EffectiveManifest,
    EvaluationEpoch,
    ManifestCohort,
    RunKind,
)
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST

D = lambda character: "sha256:" + character * 64
T0 = "2042-01-01T00:00:00.000000Z"
T1 = "2042-01-01T00:01:00.000000Z"
T2 = "2042-01-29T00:00:00.000000Z"


def _plan(**changes: object) -> ComparatorPlan:
    values: dict[str, object] = {
        "comparator_plan_id": "increment9-comparator-v1",
        "comparator_version": "v1",
        "owner_plan_digest": INCREMENT_9_SHADOW_PLAN_DIGEST,
        "eligible_universe_digest": D("1"),
        "source_portfolio_digest": D("2"),
        "rights_rules_digest": D("3"),
        "query_data_handling_digest": D("4"),
        "request_template_digest": D("5"),
        "exposure": ExposureContract(window_opens_at=T0, window_closes_at=T2),
        "budgets": BudgetCaps(),
        "sealed_at": T0,
    }
    values.update(changes)
    return ComparatorPlan(**values)  # type: ignore[arg-type]


def _manifest() -> EffectiveManifest:
    digits = "0123456789abcdef"
    return EffectiveManifest(
        manifest_id="effective-manifest-1",
        identity_digests={
            key: D(digits[index % 16])
            for index, key in enumerate(sorted(EFFECTIVE_MANIFEST_IDENTITY_KEYS))
        },
        observed_at=T0,
        identity_resolved=True,
    )


def _epoch(plan: ComparatorPlan | None = None) -> EvaluationEpoch:
    plan = plan or _plan()
    return EvaluationEpoch(
        epoch_id="epoch-9-comparator-fixture",
        plan_digest=INCREMENT_9_SHADOW_PLAN_DIGEST,
        shadow_scope_digest=D("6"),
        source_portfolio_digest=plan.source_portfolio_digest,
        prospective_universe_digest=plan.eligible_universe_digest,
        slice_rules_digest=D("7"),
        thresholds_digest=D("8"),
        comparator_rules_digest=plan.canonical_digest,
        reviewer_rules_digest=D("9"),
        budget_rules_digest=plan.budgets.canonical_digest,
        rights_rules_digest=plan.rights_rules_digest,
        opened_at=T0,
        cutoff_at=T0,
        closes_at=T2,
    )


def _cohort(
    plan: ComparatorPlan | None = None,
    epoch: EvaluationEpoch | None = None,
    manifest: EffectiveManifest | None = None,
) -> ManifestCohort:
    plan = plan or _plan()
    epoch = epoch or _epoch(plan)
    manifest = manifest or _manifest()
    return ManifestCohort(
        cohort_id="cohort-comparator-1",
        epoch_id=epoch.epoch_id,
        epoch_digest=epoch.canonical_digest,
        manifest_digest=manifest.canonical_digest,
        ordinal=1,
        previous_cohort_digest=None,
        exposure_contract_digest=D("a"),
        required_slices=("HONG_KONG", "UK"),
        opened_at=T1,
        decision_bearing=True,
    )


def _campaign():
    plan = _plan()
    epoch = _epoch(plan)
    manifest = _manifest()
    cohort = _cohort(plan, epoch, manifest)
    scopes = {
        kind: D("0123456789abcdef"[index % 16])
        for index, kind in enumerate(EXPECTED_FAULT_INVENTORY)
    }
    campaign = build_fault_campaign_manifest(
        campaign_id="fault-campaign-1",
        comparator_plan=plan,
        epoch=epoch,
        cohort=cohort,
        effective_manifest=manifest,
        production_snapshot_digest=D("b"),
        injection_scope_digests=scopes,
        sealed_at=T0,
    )
    return plan, epoch, manifest, cohort, campaign


def _request(
    plan: ComparatorPlan,
    epoch: EvaluationEpoch,
    manifest: EffectiveManifest,
    cohort: ManifestCohort,
    campaign: FaultCampaignManifest,
    **changes: object,
) -> PhaseAdmissionRequest:
    values: dict[str, object] = {
        "request_id": "admission-1",
        "campaign_digest": campaign.canonical_digest,
        "comparator_plan_digest": plan.canonical_digest,
        "epoch_digest": epoch.canonical_digest,
        "cohort_digest": cohort.canonical_digest,
        "effective_manifest_digest": manifest.canonical_digest,
        "control_ledger_digest": D("c"),
        "phase_id": campaign.phases[0].phase_id,
        "run_kind": RunKind.FAULT,
        "reservation": ResourceReservation(source_attempts=1, amplification=1),
        "completed_phase_ids": (),
        "prior_stop_reason": None,
        "observations": (),
        "requested_at": T1,
        "identities_resolved": True,
        "rights_current": True,
        "isolated_shadow": True,
        "production_nonmutation_proved": True,
        "material_change": False,
        "public_effect_requested": False,
        "production_mutation_requested": False,
    }
    values.update(changes)
    return PhaseAdmissionRequest(**values)  # type: ignore[arg-type]


def test_owner_approved_plan_binds_exact_comparators_exposure_budgets_and_order() -> None:
    plan = _plan()
    assert plan.arms == EXPECTED_COMPARATOR_ARMS
    assert plan.phase_order == EXPECTED_PHASE_ORDER
    assert plan.stop_precedence == EXPECTED_STOP_PRECEDENCE
    assert plan.exposure.semantic_cases_min == plan.exposure.semantic_cases_max == 120
    assert plan.exposure.comparator_fraction_numerator_max == 1
    assert plan.exposure.comparator_fraction_denominator == 3
    assert plan.budgets.gross_monetary_gbp_minor_units == 25_000
    assert plan.budgets.budget_transfer_allowed is False
    assert plan.excluded_live_legacy == ("BRAVE", "GDELT", "LEGACY_GEMINI")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("arms", tuple(reversed(EXPECTED_COMPARATOR_ARMS)), "arms"),
        ("phase_order", tuple(reversed(EXPECTED_PHASE_ORDER)), "phase order"),
        ("stop_precedence", tuple(reversed(EXPECTED_STOP_PRECEDENCE)), "stop precedence"),
        ("hindsight_switching_allowed", True, "anti-hindsight"),
        ("cherry_picking_allowed", True, "anti-hindsight"),
        ("backfill_allowed", True, "anti-hindsight"),
        ("denominator_repair_allowed", True, "anti-hindsight"),
    ),
)
def test_comparator_plan_rejects_reordering_and_retrospective_selection(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(ComparatorContractError, match=message):
        _plan(**{field: value})


def test_plan_and_fault_campaign_must_be_sealed_before_exposure() -> None:
    with pytest.raises(ComparatorContractError, match="before exposure"):
        _plan(sealed_at=T1)
    plan, epoch, manifest, cohort, _ = _campaign()
    with pytest.raises(ComparatorContractError, match="before exposure"):
        build_fault_campaign_manifest(
            campaign_id="late",
            comparator_plan=plan,
            epoch=epoch,
            cohort=cohort,
            effective_manifest=manifest,
            production_snapshot_digest=D("1"),
            injection_scope_digests={kind: D("1") for kind in EXPECTED_FAULT_INVENTORY},
            sealed_at=T1,
        )


def test_exposure_contract_rejects_relaxed_minimum_maximum_or_missing_policy() -> None:
    with pytest.raises(ComparatorContractError, match="semantic exposure"):
        ExposureContract(window_opens_at=T0, window_closes_at=T2, semantic_cases_max=121)
    with pytest.raises(ComparatorContractError, match="minimum exposures"):
        ExposureContract(
            window_opens_at=T0,
            window_closes_at=T2,
            minimums={"uk": 1},
        )
    with pytest.raises(ComparatorContractError, match="missing evidence"):
        ExposureContract(
            window_opens_at=T0,
            window_closes_at=T2,
            missing_evidence_policy="PASS",
        )


def test_budget_contract_is_exact_and_cannot_transfer_or_expand() -> None:
    with pytest.raises(ComparatorContractError, match="OD-011"):
        BudgetCaps(metered_api_requests=2001)
    with pytest.raises(ComparatorContractError, match="OD-011"):
        BudgetCaps(budget_transfer_allowed=True)


def test_plan_and_campaign_round_trip_exact_canonical_bytes() -> None:
    plan, _, _, _, campaign = _campaign()
    assert ComparatorPlan.from_bytes(plan.canonical_bytes) == plan
    assert FaultCampaignManifest.from_bytes(campaign.canonical_bytes) == campaign


@pytest.mark.parametrize("kind", ("unknown", "duplicate", "noncanonical"))
def test_strict_parser_rejects_unknown_duplicate_and_noncanonical(kind: str) -> None:
    raw = _plan().canonical_bytes
    if kind == "unknown":
        value = json.loads(raw)
        value["unknown"] = True
        raw = canonical_json_bytes(value)
    elif kind == "duplicate":
        raw = raw.replace(b'{"arms":', b'{"arms":null,"arms":', 1)
    else:
        raw += b"\n"
    with pytest.raises(ComparatorContractError):
        ComparatorPlan.from_bytes(raw)


def test_records_are_immutable_and_authorise_no_effect() -> None:
    plan, epoch, manifest, cohort, campaign = _campaign()
    request = _request(plan, epoch, manifest, cohort, campaign)
    for record in (plan, campaign, campaign.phases[0], request):
        assert record.authorises_live_call is False
        assert record.authorises_credentials is False
        assert record.authorises_external_egress is False
        assert record.authorises_spend is False
        assert record.authorises_publication is False
        assert record.authorises_evidence_intake is False
        assert record.authorises_canary is False
        assert record.authorises_production_mutation is False
    with pytest.raises(FrozenInstanceError):
        plan.comparator_plan_id = "changed"  # type: ignore[misc]


def test_fault_manifest_is_complete_ordered_unique_and_sealed_before_results() -> None:
    _, _, _, _, campaign = _campaign()
    assert tuple(phase.fault_kind for phase in campaign.phases) == EXPECTED_FAULT_INVENTORY
    assert tuple(phase.ordinal for phase in campaign.phases) == tuple(range(1, 19))
    assert all(
        (
            phase.expected_observation,
            phase.containment_action,
            phase.recovery_action,
        )
        == EXPECTED_FAULT_BEHAVIOUR[phase.fault_kind]
        for phase in campaign.phases
    )
    with pytest.raises(ComparatorContractError, match="ordering"):
        replace(campaign, phases=tuple(reversed(campaign.phases)))
    with pytest.raises(ComparatorContractError, match="before results"):
        replace(campaign, observations_seen_before_seal=1)
    with pytest.raises(ComparatorContractError, match="behaviour"):
        replace(
            campaign,
            phases=(
                replace(campaign.phases[0], expected_observation="OPTIMISTIC_PASS"),
                *campaign.phases[1:],
            ),
        )


def test_fault_campaign_builder_rejects_missing_scope_and_cross_epoch_binding() -> None:
    plan, epoch, manifest, cohort, _ = _campaign()
    with pytest.raises(ComparatorContractError, match="inventory"):
        build_fault_campaign_manifest(
            campaign_id="bad",
            comparator_plan=plan,
            epoch=epoch,
            cohort=cohort,
            effective_manifest=manifest,
            production_snapshot_digest=D("1"),
            injection_scope_digests={},
            sealed_at=T1,
        )
    with pytest.raises(ComparatorContractError, match="Epoch comparator"):
        build_fault_campaign_manifest(
            campaign_id="bad",
            comparator_plan=replace(plan, eligible_universe_digest=D("f")),
            epoch=epoch,
            cohort=cohort,
            effective_manifest=manifest,
            production_snapshot_digest=D("1"),
            injection_scope_digests={kind: D("1") for kind in EXPECTED_FAULT_INVENTORY},
            sealed_at=T1,
        )


def test_admission_accepts_only_exact_registered_fault_phase() -> None:
    plan, epoch, manifest, cohort, campaign = _campaign()
    controller = ApprovedPhaseAdmissionController(plan, campaign)
    receipt = controller.admit(epoch, manifest, cohort, _request(plan, epoch, manifest, cohort, campaign))
    assert receipt.disposition is AdmissionDisposition.ADMITTED
    assert receipt.decision_bearing is True
    assert receipt.runtime_authority_still_required is True
    rejected = controller.admit(
        epoch,
        manifest,
        cohort,
        _request(plan, epoch, manifest, cohort, campaign, phase_id="unknown"),
    )
    assert rejected.disposition is AdmissionDisposition.REJECTED
    assert rejected.decision_bearing is False


def test_admission_accepts_exact_ordered_comparator_phase_with_plan_manifest() -> None:
    plan, epoch, manifest, cohort, campaign = _campaign()
    controller = ApprovedPhaseAdmissionController(plan, campaign)
    first = controller.admit(
        epoch,
        manifest,
        cohort,
        _request(
            plan,
            epoch,
            manifest,
            cohort,
            campaign,
            campaign_digest=plan.canonical_digest,
            phase_id=EXPECTED_COMPARATOR_PHASE_IDS[0],
            run_kind=RunKind.COMPARATOR,
        ),
    )
    assert first.disposition is AdmissionDisposition.ADMITTED
    assert first.decision_bearing is True
    wrong_manifest = controller.admit(
        epoch,
        manifest,
        cohort,
        _request(
            plan,
            epoch,
            manifest,
            cohort,
            campaign,
            phase_id=EXPECTED_COMPARATOR_PHASE_IDS[0],
            run_kind=RunKind.COMPARATOR,
        ),
    )
    assert wrong_manifest.disposition is AdmissionDisposition.REJECTED
    second = controller.admit(
        epoch,
        manifest,
        cohort,
        _request(
            plan,
            epoch,
            manifest,
            cohort,
            campaign,
            campaign_digest=plan.canonical_digest,
            phase_id=EXPECTED_COMPARATOR_PHASE_IDS[1],
            run_kind=RunKind.COMPARATOR,
            completed_phase_ids=(EXPECTED_COMPARATOR_PHASE_IDS[0],),
        ),
    )
    assert second.disposition is AdmissionDisposition.ADMITTED


def test_phase_order_is_exact_prefix_and_prior_stop_is_durable() -> None:
    plan, epoch, manifest, cohort, campaign = _campaign()
    controller = ApprovedPhaseAdmissionController(plan, campaign)
    second = campaign.phases[1]
    out_of_order = controller.admit(
        epoch,
        manifest,
        cohort,
        _request(
            plan,
            epoch,
            manifest,
            cohort,
            campaign,
            phase_id=second.phase_id,
        ),
    )
    assert out_of_order.disposition is AdmissionDisposition.REJECTED
    admitted = controller.admit(
        epoch,
        manifest,
        cohort,
        _request(
            plan,
            epoch,
            manifest,
            cohort,
            campaign,
            phase_id=second.phase_id,
            completed_phase_ids=(campaign.phases[0].phase_id,),
        ),
    )
    assert admitted.disposition is AdmissionDisposition.ADMITTED
    stopped = controller.admit(
        epoch,
        manifest,
        cohort,
        _request(
            plan,
            epoch,
            manifest,
            cohort,
            campaign,
            prior_stop_reason=StopReason.API_BUDGET,
        ),
    )
    assert stopped.disposition is AdmissionDisposition.EARLY_STOP
    assert stopped.stop_reason is StopReason.API_BUDGET
    assert stopped.epoch_must_close is True


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"material_change": True}, StopReason.MANIFEST_IDENTITY),
        ({"identities_resolved": False}, StopReason.MANIFEST_IDENTITY),
        ({"rights_current": False}, StopReason.RIGHTS_OR_CREDENTIAL),
        ({"isolated_shadow": False}, StopReason.LEDGER_OR_CONTAINMENT),
        ({"production_nonmutation_proved": False}, StopReason.LEDGER_OR_CONTAINMENT),
        ({"public_effect_requested": True}, StopReason.PUBLIC_OR_PRODUCTION_EFFECT),
        ({"production_mutation_requested": True}, StopReason.PUBLIC_OR_PRODUCTION_EFFECT),
    ),
)
def test_admission_early_stops_drift_rights_containment_and_prohibited_effects(
    changes: dict[str, object], reason: StopReason
) -> None:
    plan, epoch, manifest, cohort, campaign = _campaign()
    receipt = ApprovedPhaseAdmissionController(plan, campaign).admit(
        epoch,
        manifest,
        cohort,
        _request(plan, epoch, manifest, cohort, campaign, **changes),
    )
    assert receipt.disposition is AdmissionDisposition.EARLY_STOP
    assert receipt.stop_reason is reason
    assert receipt.epoch_must_close is True
    assert receipt.decision_bearing is False


def test_budget_and_amplification_overrun_fail_closed() -> None:
    plan, epoch, manifest, cohort, campaign = _campaign()
    controller = ApprovedPhaseAdmissionController(plan, campaign)
    for reservation in (
        ResourceReservation(api_requests=2001),
        ResourceReservation(gross_monetary_gbp_minor_units=25_001),
        ResourceReservation(amplification=4),
        ResourceReservation(source_attempts=2, api_requests=2),
    ):
        receipt = controller.admit(
            epoch,
            manifest,
            cohort,
            _request(
                plan,
                epoch,
                manifest,
                cohort,
                campaign,
                reservation=reservation,
            ),
        )
        assert receipt.disposition is AdmissionDisposition.EARLY_STOP
        assert receipt.stop_reason is StopReason.API_BUDGET


def test_stop_precedence_is_deterministic_and_independent_of_observation_order() -> None:
    observations = (
        StopObservation.ORDINARY_PHASE_FAILURE,
        StopObservation.API_BUDGET_OVERRUN,
        StopObservation.RIGHTS_OR_CREDENTIAL_BREACH,
        StopObservation.PUBLIC_OR_PRODUCTION_EFFECT_OUTSIDE_AUTHORITY,
    )
    assert resolve_stop_reason(observations) is StopReason.PUBLIC_OR_PRODUCTION_EFFECT
    assert resolve_stop_reason(tuple(reversed(observations))) is StopReason.PUBLIC_OR_PRODUCTION_EFFECT
    assert ZERO_TOLERANCE_OBSERVATIONS <= set(StopObservation)


def test_any_early_stop_blocks_later_decision_bearing_but_allows_recovery_only() -> None:
    plan, epoch, manifest, cohort, campaign = _campaign()
    controller = ApprovedPhaseAdmissionController(plan, campaign)
    stopped = controller.admit(
        epoch,
        manifest,
        cohort,
        _request(
            plan,
            epoch,
            manifest,
            cohort,
            campaign,
            observations=(StopObservation.LEDGER_GAP,),
        ),
    )
    assert stopped.disposition is AdmissionDisposition.EARLY_STOP
    recovery_phase = campaign.phases[-1]
    recovery = controller.admit(
        epoch,
        manifest,
        cohort,
        _request(
            plan,
            epoch,
            manifest,
            cohort,
            campaign,
            phase_id=recovery_phase.phase_id,
            run_kind=RunKind.RECOVERY_PROOF,
            prior_stop_reason=StopReason.LEDGER_OR_CONTAINMENT,
        ),
    )
    assert recovery.disposition is AdmissionDisposition.RECOVERY_ONLY
    assert recovery.decision_bearing is False
    assert recovery.epoch_must_close is True


def test_request_round_trip_and_unknown_run_kind_rejected() -> None:
    plan, epoch, manifest, cohort, campaign = _campaign()
    request = _request(plan, epoch, manifest, cohort, campaign)
    assert PhaseAdmissionRequest.from_bytes(request.canonical_bytes) == request
    value = json.loads(request.canonical_bytes)
    value["run_kind"] = "PROSPECTIVE_BASELINE"
    parsed = PhaseAdmissionRequest.from_bytes(canonical_json_bytes(value))
    receipt = ApprovedPhaseAdmissionController(plan, campaign).admit(
        epoch, manifest, cohort, parsed
    )
    assert receipt.disposition is AdmissionDisposition.REJECTED


def test_request_outside_pre_registered_window_is_rejected() -> None:
    plan, epoch, manifest, cohort, campaign = _campaign()
    receipt = ApprovedPhaseAdmissionController(plan, campaign).admit(
        epoch,
        manifest,
        cohort,
        _request(
            plan,
            epoch,
            manifest,
            cohort,
            campaign,
            requested_at="2042-01-30T00:00:00.000000Z",
        ),
    )
    assert receipt.disposition is AdmissionDisposition.REJECTED
    assert receipt.stop_reason is StopReason.MANIFEST_IDENTITY


def test_epoch_manifest_and_cohort_tampering_rejects_admission() -> None:
    plan, epoch, manifest, cohort, campaign = _campaign()
    request = _request(plan, epoch, manifest, cohort, campaign)
    receipt = ApprovedPhaseAdmissionController(plan, campaign).admit(
        epoch,
        manifest,
        cohort,
        replace(request, epoch_digest=D("f")),
    )
    assert receipt.disposition is AdmissionDisposition.REJECTED
    assert receipt.stop_reason is StopReason.MANIFEST_IDENTITY
