from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST
from newsroom.increment9.review import (
    EXPECTED_ABLATIONS,
    EXPECTED_METRICS,
    EXPECTED_REVIEWERS,
    EXPECTED_REVIEW_REASONS,
    EXPECTED_SOURCE_IDS,
    EXPECTED_ZERO_TOLERANCE,
    AblationPlan,
    AdjudicationDecision,
    AssignmentManifest,
    IngestDisposition,
    MetricPlan,
    ReviewAssignment,
    ReviewCase,
    ReviewContractError,
    ReviewIngestRequest,
    ReviewLabel,
    ReviewPlan,
    ReviewerProfile,
    ReviewRole,
    ReviewUniverseSeal,
    ReviewVerdict,
    SealedEvidenceIngestController,
    build_adjudication,
    build_assignment_manifest,
    validate_label_for_assignment,
)

D = lambda character: "sha256:" + character * 64
T0 = "2042-01-01T00:00:00.000000Z"
T1 = "2042-01-29T00:00:00.000000Z"
T2 = "2042-01-29T00:01:00.000000Z"
T3 = "2042-01-29T00:02:00.000000Z"
T4 = "2042-01-29T00:03:00.000000Z"


def _ablation() -> AblationPlan:
    return AblationPlan(
        ablation_plan_id="increment9-ablation-v1",
        owner_plan_digest=INCREMENT_9_SHADOW_PLAN_DIGEST,
        axes=EXPECTED_ABLATIONS,
    )


def _metrics() -> MetricPlan:
    return MetricPlan(
        metric_plan_id="increment9-metrics-v1",
        owner_plan_digest=INCREMENT_9_SHADOW_PLAN_DIGEST,
        metrics=EXPECTED_METRICS,
        zero_tolerance=EXPECTED_ZERO_TOLERANCE,
    )


def _plan() -> ReviewPlan:
    ablation = _ablation()
    metrics = _metrics()
    return ReviewPlan(
        review_plan_id="increment9-review-v1",
        review_version="v1",
        owner_plan_digest=INCREMENT_9_SHADOW_PLAN_DIGEST,
        eligible_universe_digest=D("1"),
        reviewer_profiles=tuple(
            ReviewerProfile(role, *EXPECTED_REVIEWERS[role]) for role in ReviewRole
        ),
        ablation_plan_digest=ablation.canonical_digest,
        metric_plan_digest=metrics.canonical_digest,
        sealed_at=T0,
    )


def _ablation_digests(index: int) -> dict[str, str]:
    digits = "0123456789abcdef"
    return {
        f"{axis}:{mode}": D(digits[(index + offset) % 16])
        for offset, (axis, mode) in enumerate(
            (pair for axis, modes in EXPECTED_ABLATIONS.items() for pair in ((axis, mode) for mode in modes))
        )
    }


def _cases() -> tuple[ReviewCase, ...]:
    beats = (
        "EDUCATION_AND_FAMILIES",
        "IMMIGRATION_AND_BNO",
        "OFFICIAL_WARNINGS",
        "POLICY_AND_SERVICES",
    )
    languages = ("EN_GB", "MIXED", "ZH_HANT_HK")
    case_kinds = (
        "CORRECTION_OR_SUPERSESSION",
        "RELATED_DISTINCT_OR_FALSE_MERGE",
        "WARNING_TRANSITION",
    )
    return tuple(
        ReviewCase(
            case_id=f"case-{index:03d}",
            evidence_digest="sha256:" + f"{index:064x}",
            epoch_digest=D("2"),
            final_cohort_digest=D("3"),
            effective_manifest_digest=D("4"),
            source_id=EXPECTED_SOURCE_IDS[(index - 1) % len(EXPECTED_SOURCE_IDS)],
            jurisdiction="HONG_KONG" if index % 2 else "UK",
            language=languages[(index - 1) % len(languages)],
            source_role="COMPARATOR" if index % 3 == 0 else "OFFICIAL",
            beat=beats[(index - 1) % len(beats)],
            case_kind=case_kinds[(index - 1) % len(case_kinds)],
            changed_revision=True,
            ablation_evidence_digests=_ablation_digests(index),
        )
        for index in range(1, 121)
    )


def _universe(plan: ReviewPlan | None = None) -> ReviewUniverseSeal:
    plan = plan or _plan()
    return ReviewUniverseSeal(
        universe_id="review-universe-1",
        review_plan_digest=plan.canonical_digest,
        epoch_digest=D("2"),
        final_cohort_digest=D("3"),
        effective_manifest_digest=D("4"),
        sealed_evidence_inventory_digest=D("5"),
        cases=_cases(),
        sealed_at=T1,
    )


def _authority():
    plan = _plan()
    universe = _universe(plan)
    assignments = build_assignment_manifest(
        plan,
        universe,
        manifest_id="assignments-1",
        sealed_at=T2,
    )
    return plan, universe, assignments


def _label(
    assignment: ReviewAssignment,
    *,
    verdict: ReviewVerdict = ReviewVerdict.PASS,
    reasons: tuple[str, ...] = (),
    sealed_at: str = T3,
    **changes: object,
) -> ReviewLabel:
    values: dict[str, object] = {
        "label_id": "label-" + assignment.assignment_id,
        "assignment_digest": assignment.canonical_digest,
        "case_id": assignment.case_id,
        "case_digest": assignment.case_digest,
        "role": assignment.role,
        "reviewer_profile_digest": assignment.reviewer_profile_digest,
        "resolved_model_identity_digest": D("6" if assignment.role is ReviewRole.PRIMARY_A else "7"),
        "memory_snapshot_digest": D("8"),
        "verdict": verdict,
        "reasons": reasons,
        "confidence_ppm": 900_000,
        "research_appendix_digest": D("9"),
        "sealed_at": sealed_at,
    }
    values.update(changes)
    return ReviewLabel(**values)  # type: ignore[arg-type]


def _ingest_request(
    plan: ReviewPlan,
    universe: ReviewUniverseSeal,
    assignments: AssignmentManifest,
    **changes: object,
) -> ReviewIngestRequest:
    values: dict[str, object] = {
        "request_id": "review-ingest-1",
        "review_plan_digest": plan.canonical_digest,
        "universe_digest": universe.canonical_digest,
        "assignment_manifest_digest": assignments.canonical_digest,
        "epoch_digest": universe.epoch_digest,
        "final_cohort_digest": universe.final_cohort_digest,
        "effective_manifest_digest": universe.effective_manifest_digest,
        "sealed_evidence_inventory_digest": universe.sealed_evidence_inventory_digest,
        "requested_at": T3,
        "final_cohort_qualifies": True,
        "evidence_inventory_sealed": True,
        "prospective_only": True,
        "material_change": False,
        "result_knowledge_changed_universe": False,
    }
    values.update(changes)
    return ReviewIngestRequest(**values)  # type: ignore[arg-type]


def test_review_plan_binds_exact_cross_provider_roles_and_independence() -> None:
    plan = _plan()
    assert tuple(profile.role for profile in plan.reviewer_profiles) == tuple(ReviewRole)
    assert len({profile.provider for profile in plan.reviewer_profiles}) == 3
    assert len({profile.memory_namespace for profile in plan.reviewer_profiles}) == 3
    assert plan.sut_provider not in {profile.provider for profile in plan.reviewer_profiles}
    assert plan.reviewer_human_minutes == 0
    assert plan.human_labelled_anchor is False
    assert plan.same_family_replacement_allowed is False
    assert plan.adjudicator_replacement_allowed is False


def test_review_plan_round_trip_and_is_immutable_no_effect() -> None:
    plan = _plan()
    assert ReviewPlan.from_bytes(plan.canonical_bytes) == plan
    for flag in (
        "authorises_live_call",
        "authorises_reviewer_access",
        "authorises_credentials",
        "authorises_external_egress",
        "authorises_spend",
        "authorises_publication",
        "authorises_evidence_intake",
        "authorises_canary",
        "authorises_production_mutation",
    ):
        assert getattr(plan, flag) is False
    with pytest.raises(FrozenInstanceError):
        plan.review_plan_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("kind", ("unknown", "duplicate", "noncanonical"))
def test_strict_plan_parser_rejects_unknown_duplicate_and_noncanonical(kind: str) -> None:
    raw = _plan().canonical_bytes
    if kind == "unknown":
        value = json.loads(raw)
        value["unknown"] = True
        raw = canonical_json_bytes(value)
    elif kind == "duplicate":
        raw = raw.replace(b'{"ablation_plan_digest":', b'{"ablation_plan_digest":null,"ablation_plan_digest":', 1)
    else:
        raw += b"\n"
    with pytest.raises(ReviewContractError):
        ReviewPlan.from_bytes(raw)


def test_ablation_and_metric_plans_are_exact_and_round_trip() -> None:
    ablation = _ablation()
    metrics = _metrics()
    assert AblationPlan.from_bytes(ablation.canonical_bytes) == ablation
    assert MetricPlan.from_bytes(metrics.canonical_bytes) == metrics
    assert set(ablation.axes) == {"SOURCE", "RETRIEVAL", "GRAPHRAG", "EXTRACTION", "TRIAGE", "OPERATIONAL"}
    assert metrics.zero_tolerance == EXPECTED_ZERO_TOLERANCE
    assert metrics.threshold_change_after_results_allowed is False
    assert metrics.uncertainty_method == "WILSON_SCORE_95_FIXED_INTEGER"
    with pytest.raises(ReviewContractError, match="ablation"):
        replace(ablation, axes={"RETRIEVAL": ("HYBRID_RRF",)})
    with pytest.raises(ReviewContractError, match="metric definitions"):
        replace(metrics, metrics={})


def test_fixture_universe_proves_unique_complete_exposure_and_round_trip() -> None:
    plan = _plan()
    universe = _universe(plan)
    assert len(universe.cases) == 120
    assert len({case.case_id for case in universe.cases}) == 120
    assert len({case.evidence_digest for case in universe.cases}) == 120
    assert sum(case.source_role == "COMPARATOR" for case in universe.cases) == 40
    assert ReviewUniverseSeal.from_bytes(universe.canonical_bytes) == universe


def test_universe_rejects_duplicate_case_underexposure_and_hindsight() -> None:
    plan = _plan()
    cases = _cases()
    with pytest.raises(ReviewContractError, match="sorted|unique"):
        replace(_universe(plan), cases=cases[:-1] + (cases[0],))
    with pytest.raises(ReviewContractError, match="exposure"):
        replace(_universe(plan), cases=cases[:-1])
    with pytest.raises(ReviewContractError, match="anti-hindsight"):
        replace(_universe(plan), result_knowledge_available_at_seal=True)


def test_assignments_are_deterministic_complete_parallel_primaries_only() -> None:
    plan, universe, assignments = _authority()
    assert len(assignments.assignments) == 240
    assert AssignmentManifest.from_bytes(assignments.canonical_bytes) == assignments
    per_case: dict[str, set[ReviewRole]] = {}
    for assignment in assignments.assignments:
        per_case.setdefault(assignment.case_id, set()).add(assignment.role)
    assert all(roles == {ReviewRole.PRIMARY_A, ReviewRole.PRIMARY_B} for roles in per_case.values())
    replay = build_assignment_manifest(plan, universe, manifest_id="assignments-1", sealed_at=T2)
    assert replay.canonical_bytes == assignments.canonical_bytes


def test_assignment_rejects_replacement_incomplete_coverage_and_preseal_time() -> None:
    plan, universe, assignments = _authority()
    with pytest.raises(ReviewContractError, match="replacement"):
        replace(assignments, replacement_allowed=True)
    with pytest.raises(ReviewContractError, match="predates"):
        build_assignment_manifest(plan, universe, manifest_id="bad", sealed_at=T0)
    incomplete = replace(assignments, assignments=assignments.assignments[:-1])
    with pytest.raises(ReviewContractError, match="both primary"):
        SealedEvidenceIngestController(plan, universe, incomplete)
    tampered_items = list(assignments.assignments)
    tampered_items[0] = replace(tampered_items[0], case_digest=D("f"))
    tampered = replace(assignments, assignments=tuple(tampered_items))
    with pytest.raises(ReviewContractError, match="replay"):
        SealedEvidenceIngestController(plan, universe, tampered)


def test_primary_label_is_blinded_structured_and_bound_to_assignment() -> None:
    _, _, assignments = _authority()
    assignment = assignments.assignments[0]
    label = _label(assignment)
    assert ReviewLabel.from_bytes(label.canonical_bytes) == label
    assert validate_label_for_assignment(label, assignment) is label
    with pytest.raises(ReviewContractError, match="blinding"):
        replace(label, peer_result_visible=True)
    with pytest.raises(ReviewContractError, match="structured reason"):
        replace(label, verdict=ReviewVerdict.FAIL)
    with pytest.raises(ReviewContractError, match="assignment binding"):
        validate_label_for_assignment(replace(label, assignment_digest=D("f")), assignment)


def test_not_evaluated_is_explicit_and_cannot_be_repaired_or_hidden() -> None:
    _, _, assignments = _authority()
    missing = _label(
        assignments.assignments[0],
        verdict=ReviewVerdict.NOT_EVALUATED,
        reasons=("MISSING_EVIDENCE",),
        confidence_ppm=0,
    )
    assert missing.verdict is ReviewVerdict.NOT_EVALUATED
    assert missing.reasons == ("MISSING_EVIDENCE",)
    assert "MISSING_EVIDENCE" in EXPECTED_REVIEW_REASONS
    canonicalised = replace(missing, reasons=["MISSING_EVIDENCE"])  # type: ignore[arg-type]
    assert canonicalised.reasons == ("MISSING_EVIDENCE",)


def test_disagreement_requires_independent_adjudication_after_both_sealed() -> None:
    plan, _, assignments = _authority()
    a_assignment, b_assignment = assignments.assignments[:2]
    a = _label(a_assignment, verdict=ReviewVerdict.FAIL, reasons=("OTHER_MATERIAL_ERROR",))
    b = _label(b_assignment)
    decision = build_adjudication(
        plan,
        a,
        b,
        adjudication_id="adjudication-1",
        resolved_model_identity_digest=D("a"),
        memory_snapshot_digest=D("b"),
        final_verdict=ReviewVerdict.FAIL,
        final_reasons=("OTHER_MATERIAL_ERROR",),
        research_appendix_digest=D("c"),
        decided_at=T4,
    )
    assert AdjudicationDecision.from_bytes(decision.canonical_bytes) == decision
    assert decision.primary_a_label_digest == a.canonical_digest
    assert decision.primary_b_label_digest == b.canonical_digest
    adjudicator = next(profile for profile in plan.reviewer_profiles if profile.role is ReviewRole.ADJUDICATOR)
    assert decision.adjudicator_profile_digest != a.reviewer_profile_digest
    assert decision.adjudicator_profile_digest != b.reviewer_profile_digest
    assert adjudicator.provider == "Google"


def test_agreement_skips_adjudication_but_supported_zero_tolerance_requires_it() -> None:
    plan, _, assignments = _authority()
    a_assignment, b_assignment = assignments.assignments[:2]
    a = _label(a_assignment)
    b = _label(b_assignment)
    kwargs = dict(
        adjudication_id="adjudication-1",
        resolved_model_identity_digest=D("a"),
        memory_snapshot_digest=D("b"),
        final_verdict=ReviewVerdict.PASS,
        final_reasons=(),
        research_appendix_digest=D("c"),
        decided_at=T4,
    )
    with pytest.raises(ReviewContractError, match="agreement"):
        build_adjudication(plan, a, b, **kwargs)
    fail_a = _label(a_assignment, verdict=ReviewVerdict.FAIL, reasons=("PROVENANCE_FAILURE",))
    fail_b = _label(b_assignment, verdict=ReviewVerdict.FAIL, reasons=("PROVENANCE_FAILURE",))
    decision = build_adjudication(
        plan,
        fail_a,
        fail_b,
        **{
            **kwargs,
            "final_verdict": ReviewVerdict.FAIL,
            "final_reasons": ("PROVENANCE_FAILURE",),
        },
    )
    assert decision.final_reasons == ("PROVENANCE_FAILURE",)


def test_missing_primary_and_invalid_chronology_cannot_be_adjudicated() -> None:
    plan, _, assignments = _authority()
    a_assignment, b_assignment = assignments.assignments[:2]
    a = _label(a_assignment, verdict=ReviewVerdict.NOT_EVALUATED, reasons=("UNREVIEWABLE",))
    b = _label(b_assignment)
    with pytest.raises(ReviewContractError, match="cannot be adjudicated"):
        build_adjudication(
            plan,
            a,
            b,
            adjudication_id="bad",
            resolved_model_identity_digest=D("a"),
            memory_snapshot_digest=D("b"),
            final_verdict=ReviewVerdict.FAIL,
            final_reasons=("UNREVIEWABLE",),
            research_appendix_digest=D("c"),
            decided_at=T4,
        )


def test_adjudication_rejects_unregistered_primary_profile() -> None:
    plan, _, assignments = _authority()
    a_assignment, b_assignment = assignments.assignments[:2]
    a = _label(
        a_assignment,
        verdict=ReviewVerdict.FAIL,
        reasons=("OTHER_MATERIAL_ERROR",),
        reviewer_profile_digest=D("f"),
    )
    b = _label(b_assignment)
    with pytest.raises(ReviewContractError, match="reviewer authority"):
        build_adjudication(
            plan,
            a,
            b,
            adjudication_id="bad-reviewer",
            resolved_model_identity_digest=D("a"),
            memory_snapshot_digest=D("b"),
            final_verdict=ReviewVerdict.FAIL,
            final_reasons=("OTHER_MATERIAL_ERROR",),
            research_appendix_digest=D("c"),
            decided_at=T4,
        )
    disagree = _label(a_assignment, verdict=ReviewVerdict.FAIL, reasons=("OTHER_MATERIAL_ERROR",))
    with pytest.raises(ReviewContractError, match="predates"):
        build_adjudication(
            plan,
            disagree,
            b,
            adjudication_id="bad-time",
            resolved_model_identity_digest=D("a"),
            memory_snapshot_digest=D("b"),
            final_verdict=ReviewVerdict.FAIL,
            final_reasons=("OTHER_MATERIAL_ERROR",),
            research_appendix_digest=D("c"),
            decided_at=T2,
        )


def test_sealed_ingest_boundary_admits_exact_request_but_grants_no_runtime_access() -> None:
    plan, universe, assignments = _authority()
    controller = SealedEvidenceIngestController(plan, universe, assignments)
    request = _ingest_request(plan, universe, assignments)
    assert ReviewIngestRequest.from_bytes(request.canonical_bytes) == request
    receipt = controller.admit(request)
    assert receipt.disposition is IngestDisposition.ADMITTED_FOR_LATER_REVIEW
    assert receipt.runtime_reviewer_authority_still_required is True
    assert receipt.authorises_reviewer_access is False
    assert receipt.authorises_evidence_intake is False


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"final_cohort_qualifies": False}, "FINAL_COHORT_NOT_QUALIFIED"),
        ({"evidence_inventory_sealed": False}, "EVIDENCE_NOT_SEALED_PROSPECTIVE"),
        ({"prospective_only": False}, "EVIDENCE_NOT_SEALED_PROSPECTIVE"),
        ({"material_change": True}, "MATERIAL_CHANGE_CLOSES_EPOCH"),
        ({"result_knowledge_changed_universe": True}, "HINDSIGHT_UNIVERSE_CHANGE"),
        ({"epoch_digest": D("f")}, "AUTHORITY_BINDING_DIFFERS"),
    ),
)
def test_ingest_rejects_missing_seal_drift_hindsight_and_binding_tamper(
    changes: dict[str, object], reason: str
) -> None:
    plan, universe, assignments = _authority()
    receipt = SealedEvidenceIngestController(plan, universe, assignments).admit(
        _ingest_request(plan, universe, assignments, **changes)
    )
    assert receipt.disposition is IngestDisposition.REJECTED
    assert receipt.reason == reason
