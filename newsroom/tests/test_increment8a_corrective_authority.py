from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from newsroom.authority.canonical import digest_bytes
from newsroom.increment8.evaluation import (
    EvaluationAuthority,
    EvaluationAuthorityError,
    EvaluationCase,
    ReleaseEvidenceDecision,
    ReleaseVerdict,
    ReviewLabel,
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
    reviewable_count: int | None = None,
    positive_changed: bool = False,
    ordinary_second_reviews: bool = True,
):
    from newsroom.increment8.metrics import reviewed_case_assessment_label
    from newsroom.tests.test_increment8b_metrics import (
        _CASE_RATE_NAMES,
        _TRIAGE_NAMES,
    )

    geographies = ("GLOBAL", "HONG_KONG", "UNITED_KINGDOM")
    languages = ("EN_GB", "MIXED_EN_GB_ZH_HANT_HK", "ZH_HANT_HK")
    cases = []
    ordinary_second_count = 0
    for index in range(120):
        urgent = index % 5 == 0
        is_reviewable = reviewable and (
            reviewable_count is None or index < reviewable_count
        )
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
                RightsStatus.REVIEWABLE if is_reviewable else RightsStatus.UNREVIEWABLE
            ),
            prospective=True,
            urgent=urgent,
        )
        authority.register_case(case)
        cases.append(case)
        if not is_reviewable:
            continue
        primary_identity = REVIEWER_1 if index % 2 == 0 else REVIEWER_2
        secondary_identity = (
            REVIEWER_2 if primary_identity == REVIEWER_1 else REVIEWER_1
        )
        assessment_label = reviewed_case_assessment_label(
            case=case,
            metric_eligible={name: True for name in _CASE_RATE_NAMES},
            metric_success={name: True for name in _CASE_RATE_NAMES},
            triage_eligible={name: True for name in _TRIAGE_NAMES},
            triage_error={name: False for name in _TRIAGE_NAMES},
            slice_success=True,
        )
        authority.record_label(
            build_review_label(
                case=case,
                reviewer_identity_digest=primary_identity,
                role=ReviewRole.PRIMARY,
                label=assessment_label,
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
                    label=assessment_label,
                    blinded=True,
                    recorded_at=T3,
                )
            )
            if not urgent:
                ordinary_second_count += 1
    return tuple(cases)


def _pass_candidate(authority: EvaluationAuthority, run):
    manifest = authority.evidence_manifest_digest(run.run_id)
    from newsroom.increment8.metrics import ReviewedCaseOutcome
    from newsroom.tests.test_increment8b_metrics import (
        _CASE_RATE_NAMES,
        _TRIAGE_NAMES,
    )

    rows = authority._connection.execute(
        "SELECT c.case_bytes,p.label_bytes,(SELECT s.label_bytes FROM evaluation_labels s "
        "WHERE s.case_id=c.case_id AND s.review_role='SECONDARY') "
        "FROM evaluation_cases c JOIN evaluation_labels p ON p.case_id=c.case_id "
        "WHERE c.run_id=? AND p.review_role='PRIMARY' ORDER BY c.case_id",
        (run.run_id,),
    ).fetchall()
    outcomes = tuple(
        ReviewedCaseOutcome.build(
            case=EvaluationCase.from_canonical_bytes(bytes(case_raw)),
            review_label=ReviewLabel.from_canonical_bytes(bytes(label_raw)),
            secondary_review_label=(
                None
                if secondary_raw is None
                else ReviewLabel.from_canonical_bytes(bytes(secondary_raw))
            ),
            metric_eligible={name: True for name in _CASE_RATE_NAMES},
            metric_success={name: True for name in _CASE_RATE_NAMES},
            triage_eligible={name: True for name in _TRIAGE_NAMES},
            triage_error={name: False for name in _TRIAGE_NAMES},
            slice_success=True,
        )
        for case_raw, label_raw, secondary_raw in rows
    )
    retained_outcomes = outcomes or None
    return build_release_decision(
        run=run,
        report_canonical_bytes=_report_bytes(
            run,
            evidence_manifest_digest=manifest,
            case_outcomes=retained_outcomes,
        ),
        evidence_manifest_digest=manifest,
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
        with pytest.raises(EvaluationAuthorityError, match="urgent flag"):
            build_case(
                run=run,
                input_manifest_digest=D2,
                cutoff_at=T2,
                membership_facts=_facts(urgency="URGENT"),
                rights_status=RightsStatus.REVIEWABLE,
                prospective=True,
                urgent=False,
            )
        urgent_case = build_case(
            run=run,
            input_manifest_digest=D2,
            cutoff_at=T2,
            membership_facts=_facts(urgency="URGENT"),
            rights_status=RightsStatus.REVIEWABLE,
            prospective=True,
            urgent=True,
        )
        direct_payload = dict(urgent_case.payload)
        direct_payload["urgent"] = False
        with pytest.raises(EvaluationAuthorityError, match="membership"):
            authority.register_case(EvaluationCase.build(direct_payload))
        authority.register_case(case)
        duplicate_event = build_case(
            run=run,
            input_manifest_digest=D1,
            cutoff_at=T3,
            membership_facts=_facts(urgency="URGENT"),
            rights_status=RightsStatus.REVIEWABLE,
            prospective=True,
            urgent=True,
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
        from newsroom.increment8.metrics import (
            ReviewedCaseOutcome,
            reviewed_case_assessment_label,
        )
        from newsroom.tests.test_increment8b_metrics import (
            _CASE_RATE_NAMES,
            _TRIAGE_NAMES,
        )

        metric_eligible = {name: True for name in _CASE_RATE_NAMES}
        metric_success = {name: True for name in _CASE_RATE_NAMES}
        metric_success["candidate_precision"] = False
        triage_eligible = {name: True for name in _TRIAGE_NAMES}
        triage_error = {name: False for name in _TRIAGE_NAMES}
        primary = build_review_label(
            case=case,
            reviewer_identity_digest=REVIEWER_1,
            role=ReviewRole.PRIMARY,
            label=reviewed_case_assessment_label(
                case=case,
                metric_eligible=metric_eligible,
                metric_success=metric_success,
                triage_eligible=triage_eligible,
                triage_error=triage_error,
                slice_success=True,
            ),
            blinded=True,
            recorded_at=T3,
        )
        authority.record_label(primary)
        outcome = ReviewedCaseOutcome.build(
            case=case,
            review_label=primary,
            metric_eligible=metric_eligible,
            metric_success=metric_success,
            triage_eligible=triage_eligible,
            triage_error=triage_error,
            slice_success=True,
        )
        manifest = authority.evidence_manifest_digest(run.run_id)
        decision = build_release_decision(
            run=run,
            report_canonical_bytes=_report_bytes(
                run,
                status="FAIL",
                evidence_manifest_digest=manifest,
                case_outcomes=(outcome,),
            ),
            evidence_manifest_digest=manifest,
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


def test_complete_valid_exposure_reaches_authorised_release_decision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_REPOSITORY", "fol2/newsroom")
    monkeypatch.setenv(
        "GITHUB_SHA",
        subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip(),
    )
    connection, authority, run = _registered(tmp_path)
    try:
        _populate(authority, run)
        authority.decide_release(_pass_candidate(authority, run))
        assert connection.execute(
            "SELECT verdict FROM evaluation_release_decisions WHERE run_id=?",
            (run.run_id,),
        ).fetchone() == ("PASS",)
    finally:
        connection.close()


def test_positive_changed_only_exposure_fails_frozen_strata(tmp_path: Path) -> None:
    connection, authority, run = _registered(tmp_path)
    try:
        _populate(authority, run, positive_changed=True)
        with pytest.raises(EvaluationAuthorityError, match="retained Metric Report"):
            authority.decide_release(_pass_candidate(authority, run))
    finally:
        connection.close()


def test_all_unreviewable_exposure_cannot_vacuously_pass(tmp_path: Path) -> None:
    connection, authority, run = _registered(tmp_path)
    try:
        _populate(authority, run, reviewable=False)
        with pytest.raises(EvaluationAuthorityError, match="outcomes differ"):
            authority.decide_release(_pass_candidate(authority, run))
    finally:
        connection.close()


def test_unreviewable_cases_do_not_fill_reviewed_exposure(tmp_path: Path) -> None:
    connection, authority, run = _registered(tmp_path)
    try:
        _populate(authority, run, reviewable_count=2)
        with pytest.raises(EvaluationAuthorityError, match="retained Metric Report"):
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
    minimal = {
        "schema_version": "newsroom.increment8.metric-report.v1",
        "payload": {
            "run_id": run.run_id,
            "run_digest": run.digest,
            "metric_status": "PASS",
            "slice_status": "PASS",
            "zero_tolerance_status": "PASS",
            "overall_status": "PASS",
            "production_activation_authorised": False,
            "live_shadow_execution_authorised": False,
        },
    }
    with pytest.raises(EvaluationAuthorityError, match="canonical reconstruction"):
        build_release_decision(
            run=run,
            report_canonical_bytes=json.dumps(
                minimal, sort_keys=True, separators=(",", ":")
            ).encode(),
            evidence_manifest_digest=D1,
            verdict=ReleaseVerdict.PASS,
            owner_identity_digest=OWNER,
            decided_at=T5,
        )
    inconsistent = json.loads(_report_bytes(run))
    inconsistent["payload"]["metric_status"] = "FAIL"
    raw = json.dumps(inconsistent, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(EvaluationAuthorityError, match="canonical reconstruction"):
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
        manifest = authority.evidence_manifest_digest(retained_run.run_id)
        report_raw = _report_bytes(
            retained_run, status="FAIL", evidence_manifest_digest=manifest
        )
        report = json.loads(report_raw)
        direct = ReleaseEvidenceDecision.build(
            {
                "run_id": retained_run.run_id,
                "run_digest": retained_run.digest,
                "report_digest": _digest(500),
                "metric_report": report,
                "evidence_manifest_digest": manifest,
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
        contradictory_payload = dict(direct.payload)
        contradictory_payload["report_digest"] = digest_bytes(report_raw)
        contradictory_payload["metrics_passed"] = True
        contradictory = ReleaseEvidenceDecision.build(contradictory_payload)
        with pytest.raises(EvaluationAuthorityError, match="decision gates"):
            authority.decide_release(contradictory)
    finally:
        connection.close()


@pytest.mark.parametrize("verdict", [ReleaseVerdict.FAIL, ReleaseVerdict.INCONCLUSIVE])
def test_non_pass_decisions_reject_foreign_reviewed_case_evidence(
    tmp_path: Path, verdict: ReleaseVerdict
) -> None:
    connection, authority, run = _registered(tmp_path / verdict.value.lower())
    try:
        manifest = authority.evidence_manifest_digest(run.run_id)
        report_raw = _report_bytes(
            run, status="FAIL", evidence_manifest_digest=manifest
        )
        decision = build_release_decision(
            run=run,
            report_canonical_bytes=report_raw,
            evidence_manifest_digest=manifest,
            verdict=verdict,
            owner_identity_digest=OWNER,
            decided_at=T5,
            early_stopped=True,
        )
        with pytest.raises(EvaluationAuthorityError, match="outcomes differ"):
            authority.decide_release(decision)
    finally:
        connection.close()


def test_release_decision_retains_actual_zero_tolerance_failure_count() -> None:
    _, _, run = _records()
    decision = build_release_decision(
        run=run,
        report_canonical_bytes=_report_bytes(
            run,
            status="FAIL",
            zero_failures=("temporal_rewrite", "rights_breach"),
        ),
        evidence_manifest_digest=D2,
        verdict=ReleaseVerdict.FAIL,
        owner_identity_digest=OWNER,
        decided_at=T5,
    )
    assert decision.payload["zero_tolerance_failure_count"] == 2
