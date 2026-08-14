from __future__ import annotations

import json
from pathlib import Path

import pytest

from newsroom.authority.canonical import digest_bytes
from newsroom.increment8.evaluation import (
    EvaluationAuthority,
    EvaluationAuthorityError,
    EvaluationCase,
    ReleaseEvidenceDecision,
    ReleaseVerdict,
    ReviewRole,
    RightsStatus,
    RunKind,
    build_adjudication,
    build_case,
    build_evaluation_plan,
    build_release_decision,
    build_review_label,
    freeze_epoch,
    open_run,
)
from newsroom.tests.test_increment8a_evaluation_authority import (
    D1,
    D2,
    OWNER,
    REVIEWER_1,
    REVIEWER_2,
    T0,
    T1,
    T2,
    T3,
    T4,
    T5,
    _database,
    _facts,
    _plan_kwargs,
    _records,
    _report_bytes,
)


def _digest(index: int) -> str:
    return f"sha256:{index:064x}"


def _registered(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    connection = _database(tmp_path / "authority.sqlite3")
    authority = EvaluationAuthority(connection)
    plan, epoch, run = _records()
    authority.register_plan(plan)
    authority.register_epoch(epoch)
    authority.register_run(run)
    return connection, authority, run


def _populate(
    authority: EvaluationAuthority,
    run,
    *,
    reviewable: bool = True,
    positive_changed: bool = False,
    ordinary_second_reviews: bool = True,
):
    geographies = ("GLOBAL", "HONG_KONG", "UNITED_KINGDOM")
    languages = ("EN_GB", "MIXED_EN_GB_ZH_HANT_HK", "ZH_HANT_HK")
    cases = []
    ordinary_second_count = 0
    for index in range(120):
        urgent = index % 5 == 0
        case = build_case(
            run=run,
            input_manifest_digest=_digest(index + 100),
            cutoff_at=T2,
            membership_facts=_facts(
                geography=geographies[index % len(geographies)],
                language=languages[index % len(languages)],
                urgency="URGENT" if urgent else "ROUTINE",
                failures=2,
                candidate="CANDIDATE" if positive_changed else "NO_CANDIDATE",
                transition="CHANGED" if positive_changed else "UNCHANGED",
            ),
            rights_status=(
                RightsStatus.REVIEWABLE if reviewable else RightsStatus.UNREVIEWABLE
            ),
            prospective=True,
            urgent=urgent,
        )
        authority.register_case(case)
        cases.append(case)
        if not reviewable:
            continue
        primary_identity = REVIEWER_1 if index % 2 == 0 else REVIEWER_2
        secondary_identity = (
            REVIEWER_2 if primary_identity == REVIEWER_1 else REVIEWER_1
        )
        authority.record_label(
            build_review_label(
                case=case,
                reviewer_identity_digest=primary_identity,
                role=ReviewRole.PRIMARY,
                label="expected-route",
                blinded=True,
                recorded_at=T3,
            )
        )
        if urgent or (ordinary_second_reviews and ordinary_second_count < 20):
            authority.record_label(
                build_review_label(
                    case=case,
                    reviewer_identity_digest=secondary_identity,
                    role=ReviewRole.SECONDARY,
                    label="expected-route",
                    blinded=True,
                    recorded_at=T3,
                )
            )
            if not urgent:
                ordinary_second_count += 1
    return tuple(cases)


def _pass_candidate(authority: EvaluationAuthority, run):
    return build_release_decision(
        run=run,
        report_canonical_bytes=_report_bytes(run),
        evidence_manifest_digest=authority.evidence_manifest_digest(run.run_id),
        verdict=ReleaseVerdict.PASS,
        owner_identity_digest=OWNER,
        decided_at=T5,
    )


def test_connection_must_be_transaction_free_with_foreign_keys_active(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path / "authority.sqlite3")
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        with pytest.raises(EvaluationAuthorityError, match="foreign keys"):
            EvaluationAuthority(connection)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN")
        with pytest.raises(EvaluationAuthorityError, match="caller-owned"):
            EvaluationAuthority(connection)
        assert connection.in_transaction is True
        connection.execute("ROLLBACK")
    finally:
        connection.close()


def test_plan_epoch_run_case_and_review_chronology_is_enforced() -> None:
    plan = build_evaluation_plan(
        approved_by_digest=OWNER,
        approved_at=T2,
        component_manifest_digest=D1,
        **_plan_kwargs(),
    )
    with pytest.raises(EvaluationAuthorityError, match="chronology"):
        freeze_epoch(
            plan=plan,
            target_manifest_digest=D1,
            universe_manifest_digest=D2,
            sampling_method_digest=D1,
            cutoff_at=T0,
            opened_at=T1,
        )
    _, epoch, _ = _records()
    with pytest.raises(EvaluationAuthorityError, match="chronology"):
        open_run(
            epoch=epoch, kind=RunKind.QUALIFICATION, started_at="2026-08-13T00:00:00Z"
        )
    _, _, run = _records()
    with pytest.raises(EvaluationAuthorityError, match="chronology"):
        build_case(
            run=run,
            input_manifest_digest=D1,
            cutoff_at=T0,
            membership_facts=_facts(),
            rights_status=RightsStatus.REVIEWABLE,
            prospective=True,
        )


def test_authorised_human_roles_and_same_role_uniqueness_are_enforced(
    tmp_path: Path,
) -> None:
    connection, authority, run = _registered(tmp_path)
    try:
        case = build_case(
            run=run,
            input_manifest_digest=D1,
            cutoff_at=T2,
            membership_facts=_facts(),
            rights_status=RightsStatus.REVIEWABLE,
            prospective=True,
        )
        authority.register_case(case)
        unauthorised = build_review_label(
            case=case,
            reviewer_identity_digest=_digest(999),
            role=ReviewRole.PRIMARY,
            label="route-a",
            blinded=True,
            recorded_at=T3,
        )
        with pytest.raises(EvaluationAuthorityError, match="authorised human"):
            authority.record_label(unauthorised)
        primary = build_review_label(
            case=case,
            reviewer_identity_digest=REVIEWER_1,
            role=ReviewRole.PRIMARY,
            label="route-a",
            blinded=True,
            recorded_at=T3,
        )
        authority.record_label(primary)
        same_role = build_review_label(
            case=case,
            reviewer_identity_digest=REVIEWER_2,
            role=ReviewRole.PRIMARY,
            label="route-b",
            blinded=True,
            recorded_at=T3,
        )
        with pytest.raises(EvaluationAuthorityError, match="one label per role"):
            authority.record_label(same_role)
        secondary = build_review_label(
            case=case,
            reviewer_identity_digest=REVIEWER_2,
            role=ReviewRole.SECONDARY,
            label="route-b",
            blinded=True,
            recorded_at=T3,
        )
        authority.record_label(secondary)
        unauthorised_adjudication = build_adjudication(
            case=case,
            primary=primary,
            secondary=secondary,
            adjudicator_identity_digest=_digest(998),
            final_label="route-a",
            decided_at=T4,
        )
        with pytest.raises(EvaluationAuthorityError, match="adjudicator"):
            authority.record_adjudication(unauthorised_adjudication)
    finally:
        connection.close()


def test_case_membership_and_distinct_event_manifest_are_reconstructed(
    tmp_path: Path,
) -> None:
    connection, authority, run = _registered(tmp_path)
    try:
        case = build_case(
            run=run,
            input_manifest_digest=D1,
            cutoff_at=T2,
            membership_facts=_facts(),
            rights_status=RightsStatus.REVIEWABLE,
            prospective=True,
        )
        forged_payload = dict(case.payload)
        forged_payload["required_slices"] = ["INVENTED"]
        with pytest.raises(EvaluationAuthorityError, match="membership"):
            authority.register_case(EvaluationCase.build(forged_payload))
        authority.register_case(case)
        duplicate_event = build_case(
            run=run,
            input_manifest_digest=D1,
            cutoff_at=T3,
            membership_facts=_facts(urgency="URGENT"),
            rights_status=RightsStatus.REVIEWABLE,
            prospective=True,
        )
        with pytest.raises(EvaluationAuthorityError, match="distinct events"):
            authority.register_case(duplicate_event)
    finally:
        connection.close()


def test_release_decision_seals_the_complete_evidence_manifest(tmp_path: Path) -> None:
    connection, authority, run = _registered(tmp_path)
    try:
        case = build_case(
            run=run,
            input_manifest_digest=D1,
            cutoff_at=T2,
            membership_facts=_facts(),
            rights_status=RightsStatus.REVIEWABLE,
            prospective=True,
        )
        authority.register_case(case)
        decision = build_release_decision(
            run=run,
            report_canonical_bytes=_report_bytes(run, status="FAIL"),
            evidence_manifest_digest=authority.evidence_manifest_digest(run.run_id),
            verdict=ReleaseVerdict.INCONCLUSIVE,
            owner_identity_digest=OWNER,
            decided_at=T5,
            early_stopped=True,
        )
        authority.decide_release(decision)
        later_case = build_case(
            run=run,
            input_manifest_digest=D2,
            cutoff_at=T3,
            membership_facts=_facts(),
            rights_status=RightsStatus.REVIEWABLE,
            prospective=True,
        )
        with pytest.raises(EvaluationAuthorityError, match="sealed"):
            authority.register_case(later_case)
        later_label = build_review_label(
            case=case,
            reviewer_identity_digest=REVIEWER_1,
            role=ReviewRole.PRIMARY,
            label="route-a",
            blinded=True,
            recorded_at=T4,
        )
        with pytest.raises(EvaluationAuthorityError, match="sealed"):
            authority.record_label(later_label)
    finally:
        connection.close()


def test_complete_valid_exposure_reaches_only_the_corrective_blockade(
    tmp_path: Path,
) -> None:
    connection, authority, run = _registered(tmp_path)
    try:
        _populate(authority, run)
        with pytest.raises(EvaluationAuthorityError, match="corrective readiness"):
            authority.decide_release(_pass_candidate(authority, run))
    finally:
        connection.close()


def test_positive_changed_only_exposure_fails_frozen_strata(tmp_path: Path) -> None:
    connection, authority, run = _registered(tmp_path)
    try:
        _populate(authority, run, positive_changed=True)
        with pytest.raises(EvaluationAuthorityError, match="stratum"):
            authority.decide_release(_pass_candidate(authority, run))
    finally:
        connection.close()


def test_all_unreviewable_exposure_cannot_vacuously_pass(tmp_path: Path) -> None:
    connection, authority, run = _registered(tmp_path)
    try:
        _populate(authority, run, reviewable=False)
        with pytest.raises(EvaluationAuthorityError, match="reviewable exposure"):
            authority.decide_release(_pass_candidate(authority, run))
    finally:
        connection.close()


def test_mandatory_second_reviews_do_not_satisfy_ordinary_sample(
    tmp_path: Path,
) -> None:
    connection, authority, run = _registered(tmp_path)
    try:
        _populate(authority, run, ordinary_second_reviews=False)
        with pytest.raises(EvaluationAuthorityError, match="second-review exposure"):
            authority.decide_release(_pass_candidate(authority, run))
    finally:
        connection.close()


def test_report_is_retained_and_reconstructed_not_a_caller_boolean(
    tmp_path: Path,
) -> None:
    _, _, run = _records()
    inconsistent = json.loads(_report_bytes(run))
    inconsistent["payload"]["metric_status"] = "FAIL"
    raw = json.dumps(inconsistent, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(EvaluationAuthorityError, match="internally inconsistent"):
        build_release_decision(
            run=run,
            report_canonical_bytes=raw,
            evidence_manifest_digest=D1,
            verdict=ReleaseVerdict.PASS,
            owner_identity_digest=OWNER,
            decided_at=T5,
        )

    connection, authority, retained_run = _registered(tmp_path / "direct")
    try:
        report_raw = _report_bytes(retained_run, status="FAIL")
        report = json.loads(report_raw)
        direct = ReleaseEvidenceDecision.build(
            {
                "run_id": retained_run.run_id,
                "run_digest": retained_run.digest,
                "report_digest": _digest(500),
                "metric_report": report,
                "evidence_manifest_digest": authority.evidence_manifest_digest(
                    retained_run.run_id
                ),
                "verdict": ReleaseVerdict.INCONCLUSIVE.value,
                "owner_identity_digest": OWNER,
                "decided_at": T5,
                "metrics_passed": False,
                "required_slices_passed": False,
                "zero_tolerance_failure_count": 1,
                "early_stopped": True,
                "production_activation_authorised": False,
            }
        )
        assert digest_bytes(report_raw) != direct.payload["report_digest"]
        with pytest.raises(EvaluationAuthorityError, match="Report digest"):
            authority.decide_release(direct)
    finally:
        connection.close()
